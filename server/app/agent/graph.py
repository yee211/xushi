"""LangGraph orchestration for all model-driven Agent queries.

No checkpoint/store, retries, provider SDK migration, or channel side effects.
Each invocation owns its graph, runtime and state. Credentials/tools stay out of state.
"""
import json
import re
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from typing import TypedDict
from urllib.parse import urlsplit

import httpx
from langgraph.graph import END, START, StateGraph
from langsmith import tracing_context

from . import loop
from .completion import COMPLETION_PROMPT, Completion, promises_work
from .course_reply import CourseComment, course_facts, render_courses
from .other_reply import contextual_question, group_request, mentions_others, mixed_people, render_other_facts


class QueryState(TypedDict, total=False):
    messages: list[dict]
    facts: list[dict]
    rounds: int
    reply: dict
    route: str
    answer: dict | None
    corrected: bool


class QueryRun:
    def __init__(self, tools, question: str, history: list | None, credentials=None):
        self.tools = tools
        self.question = question
        self.history = history
        self.scope_question = contextual_question(question, history)
        self.base_url, self.api_key, self.model_name = credentials or loop.agent_config()
        self.config = loop.get_llm_config("agent")
        self.skills = loop.build_skills(tools)
        # Recovery snapshot belongs only to this invocation, never a module global.
        self.facts = []
        self._people = None

    def other_scope(self):
        if mentions_others(self.scope_question):
            return True
        if self._people is None:
            self._people = self.tools.list_other_people().get("people") or []
        if not self._people:
            return False
        return mentions_others(self.scope_question, self._people) or group_request(self.scope_question)

    def scope_complete(self, facts):
        if not self.other_scope():
            return True
        called = {f["skill"] for f in facts}
        if re.search(r"有空|空闲|空档|忙不忙|忙吗|空不空", self.scope_question):
            results = [f["result"] for f in facts if f["skill"] == "check_group_availability"]
            return any(r.get("error") or (
                any(p["role"] == "other" for p in r.get("participants", [])) and
                (not mixed_people(self.scope_question) or any(p["role"] == "me" for p in r["participants"]))) for r in results)
        if re.search(r"课|安排", self.scope_question) and not re.search(r"添加|加一下|保存|绑定|名单|列表", self.scope_question):
            return "query_other_day_courses" in called and (not mixed_people(self.scope_question) or "query_day_courses" in called)
        return True

    def other_error(self, facts):
        names = {"query_other_day_courses", "check_group_availability", "add_other_schedule"}
        if any(f["skill"] in names for f in facts):
            names.add("query_day_courses")
        relevant = [f for f in facts if f["skill"] in names]
        # A later retry of the same operation may recover an earlier error.
        latest = {}
        for fact in relevant:
            latest[(fact["skill"], str(fact.get("arguments")))] = fact["result"]
        for item in latest.values():
            if item.get("error") and item.get("message"):
                answer = self.answer(facts, item["message"])
                answer["_completion_status"] = "needs_input" if item["error"] in {
                    "AMBIGUOUS_PERSON", "AMBIGUOUS_SCHEDULE", "ADD_NEEDS_INPUT", "NO_OTHER_SCHEDULES", "PERSON_NOT_FOUND"} else "failed"
                return answer
        return None

    def answer(self, facts, content):
        return {"answer": content, "skills": [f["skill"] for f in facts],
                "tool_result": {"skills": facts}, "resolved_context": loop._extract_context_entities(facts)}

    def saved_answer(self, facts):
        error = self.other_error(facts)
        if error:
            return error
        if not self.scope_complete(facts):
            return None
        rendered = render_other_facts(facts, self.tools.context.now.date())
        if rendered:
            return self.answer(facts, rendered)
        bundle = course_facts(facts, self.question)
        if bundle is None:
            return None
        return self.answer(facts, render_courses(bundle, self.tools.context.now.date()))

    def initialize(self, state: QueryState) -> dict:
        messages = loop._api_messages(loop.SYSTEM_PROMPT + COMPLETION_PROMPT, self.history,
            json.dumps({"服务端当前时间": self.tools.context.now.isoformat(),
                        "时区": self.tools.context.timezone, "用户消息": self.question}, ensure_ascii=False))
        return {"messages": messages, "facts": [], "rounds": 0, "answer": None, "corrected": False}

    def model(self, state: QueryState) -> dict:
        if state["rounds"] >= loop.MAX_ROUNDS:
            loop.logger.warning("Agent failed: maximum_rounds")
            loop.llm_circuit_breaker.record_failure("agent loop exhausted maximum rounds")
            return {"route": "recover"}
        loop.remaining()
        payload = {"model": self.model_name, "temperature": 0.2,
                   "max_tokens": int(self.config.get("max_tokens") or loop.MAX_TOKENS),
                   "messages": state["messages"], "tools": loop.openai_tools(self.skills), "tool_choice": "auto",
                   "response_format": {"type": "json_object"}}
        if self.scope_complete(state["facts"]) and course_facts(state["facts"], self.question) is not None:
            payload["messages"] = state["messages"] + [{"role": "system", "content":
                '课程列表由服务端使用工具事实生成。只输出 JSON 对象 {"closing":"一句可选的自然提醒"}。'
                '不要输出日期、课程列表或同步状态；没有适合的提醒就返回 {"closing":""}。'}]
            payload["response_format"] = {"type": "json_object"}
            payload["tool_choice"] = "none"
        if urlsplit(self.base_url).hostname == "api.deepseek.com":
            payload["thinking"] = {"type": "enabled" if self.config.get("enable_thinking") else "disabled"}
        else:
            payload["enable_thinking"] = bool(self.config.get("enable_thinking", False))
        response = loop._post_llm(f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=float(self.config.get("timeout_seconds") or loop._timeout()), json=payload)
        response.raise_for_status()
        loop.remaining()
        choice = response.json()["choices"][0]
        if choice.get("finish_reason") == "length":
            return {"rounds": state["rounds"] + 1, "route": "recover"}
        reply = choice["message"]
        return {"rounds": state["rounds"] + 1, "reply": reply,
                "route": "tools" if reply.get("tool_calls") else "validate"}

    def execute_tools(self, state: QueryState) -> dict:
        reply = state["reply"]
        calls = reply["tool_calls"]
        assistant = {"role": "assistant", "content": str(reply.get("content") or ""), "tool_calls": calls}
        if reply.get("reasoning_content") is not None:
            assistant["reasoning_content"] = reply["reasoning_content"]
        if len(calls) == 1:
            results = [loop._execute_tool_call(self.skills, calls[0])]
        else:
            with ThreadPoolExecutor(max_workers=min(len(calls), 6)) as executor:
                futures = [executor.submit(copy_context().run, loop._execute_tool_call, self.skills, call)
                           for call in calls]
                results = [future.result() for future in futures]
        facts = state["facts"] + [fact for fact, _ in results]
        messages = state["messages"] + [assistant] + [msg for _, msg in results]
        self.facts = facts
        return {"facts": facts, "messages": messages, "route": "model"}

    def unfinished(self, state: QueryState) -> dict:
        # One correction at most, within the original round/deadline budget.
        if not state.get("corrected") and state["rounds"] < loop.MAX_ROUNDS:
            return {"corrected": True, "route": "model", "messages": state["messages"] + [
                {"role": "system", "content": "上一条回复没有完成用户请求，不能以稍等或稍后回复结束。"
                 "请现在调用对应工具获取本轮事实；缺少信息请明确提问，不能承诺不存在的后台任务。"}]}
        loop.llm_circuit_breaker.record_failure("completion correction exhausted")
        return {"answer": None, "route": "done"}

    def validate(self, state: QueryState) -> dict:
        facts = state["facts"]
        error = self.other_error(facts)
        if error:
            return {"answer": error, "route": "done"}
        content = str(state["reply"].get("content") or "").strip()
        content = re.sub(r"\s*\[消息时间[:：].*?\]\s*$", "", content, flags=re.DOTALL).strip()
        content = content.replace("😂", "").strip()
        completion_status = None
        complete_scope = self.scope_complete(facts)
        bundle = course_facts(facts, self.question) if complete_scope else None
        # Preserve verified courses even if the optional model comment is malformed.
        # Older providers may return plain text; the same execution checks still apply.
        if bundle is None and content.startswith(("{", "[")):
            try:
                completion = Completion.model_validate_json(content)
            except ValueError:
                return self.unfinished(state)
            if completion.status == "pending" or completion.task_id is not None:
                return self.unfinished(state)
            content = completion.answer
            if completion.status == "needs_input" and not re.search(r"[？?]|请.{0,8}(?:提供|补充|选择|说明)|哪", content):
                return self.unfinished(state)
            completion_status = completion.status
        if completion_status == "needs_input" and not promises_work(content):
            context = json.dumps([f["result"] for f in facts], ensure_ascii=False, default=str)
            if loop._grounded(content, context) and loop._facts_grounded(
                    content, facts, "", today=self.tools.context.now.date()):
                loop.llm_circuit_breaker.record_success()
                answer = self.answer(facts, content)
                answer["_completion_status"] = "needs_input"
                return {"answer": answer, "route": "done"}
        if not complete_scope:
            return self.unfinished(state)
        rendered = render_other_facts(facts, self.tools.context.now.date())
        if rendered:
            return {"answer": self.answer(facts, rendered), "route": "done"}
        if bundle is not None:
            try:
                comment = CourseComment.model_validate_json(content).closing
            except ValueError:
                comment = ""
            if promises_work(comment):
                comment = ""
            candidate = render_courses(bundle, self.tools.context.now.date(), comment)
            if comment and not (loop._grounded(candidate, json.dumps([f["result"] for f in facts],
                                                                     ensure_ascii=False, default=str))
                                and loop._facts_grounded(candidate, facts, self.question,
                                                         today=self.tools.context.now.date())):
                candidate = render_courses(bundle, self.tools.context.now.date())
            loop.llm_circuit_breaker.record_success()
            return {"answer": self.answer(facts, candidate), "route": "done"}
        from .orchestrator import parse_intent
        intent = parse_intent(self.question, self.tools.context.now.date())
        required = {"QUERY_DAY": {"query_day_courses", "query_other_day_courses"},
                    "QUERY_AVAILABILITY": {"query_day_courses", "query_other_day_courses", "check_group_availability"},
                    "QUERY_COURSE_ON_DAY": {"query_day_courses", "query_other_day_courses"},
                    "QUERY_WEEK": {"query_week_courses"},
                    "QUERY_NEXT": {"get_next_course"}, "FIND_COURSE": {"find_course"}, "QUERY_WEATHER": {"get_weather"}}
        expected_skills = required.get(intent.name)
        missing = bool(expected_skills) and not any(f["skill"] in expected_skills for f in facts)
        if promises_work(content) or (missing and loop._facts_grounded(
                content, facts, self.question, today=self.tools.context.now.date())
                and not re.search(r"[？?]|无法|暂时|失败|不可用|未绑定|未导入", content)):
            return self.unfinished(state)
        context = json.dumps([f["result"] for f in facts if not f["result"].get("error")],
                             ensure_ascii=False, default=str) + " " + self.tools.context.now.strftime("%H:%M")
        if content and loop._grounded(content, context) and loop._facts_grounded(
                content, facts, self.question, today=self.tools.context.now.date()):
            loop.llm_circuit_breaker.record_success()
            answer = self.answer(facts, content)
            if completion_status in {"failed", "needs_input"}:
                answer["_completion_status"] = completion_status
            return {"answer": answer, "route": "done"}
        loop.logger.warning("Agent response rejected: %s", "empty" if not content else "grounding_validation")
        loop.llm_circuit_breaker.record_failure("empty or ungrounded LLM response")
        return {"answer": None, "route": "done"}

    def recover(self, state: QueryState) -> dict:
        return {"answer": self.saved_answer(state.get("facts", self.facts))}

    def guarded(self, node):
        def invoke(state: QueryState) -> dict:
            try:
                return node(state)
            except Exception as error:
                # Type only: never log request headers, provider bodies or user messages.
                status = error.response.status_code if isinstance(error, httpx.HTTPStatusError) else None
                loop.logger.warning("Agent graph node failed: node=%s type=%s status=%s",
                                    node.__name__, type(error).__name__, status)
                loop.llm_circuit_breaker.record_failure(error)
                return {"route": "recover"}
        return invoke


def build_graph(runtime: QueryRun):
    builder = StateGraph(QueryState)
    builder.add_node("initialize", runtime.guarded(runtime.initialize))
    builder.add_node("model", runtime.guarded(runtime.model))
    builder.add_node("tools", runtime.guarded(runtime.execute_tools))
    builder.add_node("validate", runtime.guarded(runtime.validate))
    builder.add_node("recover", runtime.recover)
    builder.add_edge(START, "initialize")
    builder.add_conditional_edges("initialize", lambda state: state.get("route", "model"),
                                  {"model": "model", "recover": "recover"})
    builder.add_conditional_edges("model", lambda state: state["route"],
                                  {"tools": "tools", "validate": "validate", "recover": "recover"})
    builder.add_conditional_edges("tools", lambda state: state["route"],
                                  {"model": "model", "recover": "recover"})
    builder.add_conditional_edges("validate", lambda state: state["route"],
                                  {"done": END, "recover": "recover", "model": "model"})
    builder.add_edge("recover", END)
    return builder.compile()


def run(tools, message: str, history: list | None = None) -> dict | None:
    credentials = loop.agent_config()
    if not all(credentials):
        return None
    runtime = QueryRun(tools, message, history, credentials)
    try:
        # Deliberately prevent graph tracing from exporting history/tool facts.
        with tracing_context(enabled=False):
            result = build_graph(runtime).invoke({}, {"recursion_limit": 4 * loop.MAX_ROUNDS + 5})
        return result.get("answer")
    except Exception as error:
        loop.logger.warning("Agent graph failed: %s", type(error).__name__)
        loop.llm_circuit_breaker.record_failure(error)
        return runtime.saved_answer(runtime.facts)
