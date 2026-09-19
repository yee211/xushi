package io.github.yee211.classschedule;

import android.app.Dialog;
import android.content.Context;
import android.content.DialogInterface;
import android.graphics.Color;
import android.graphics.PorterDuff;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.net.http.SslError;
import android.os.Build;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.View;
import android.view.ViewGroup;
import android.view.Window;
import android.view.WindowManager;
import android.webkit.CookieManager;
import android.webkit.JavascriptInterface;
import android.webkit.SslErrorHandler;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;

import androidx.webkit.WebViewCompat;
import androidx.webkit.WebViewFeature;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

@CapacitorPlugin(name = "AcademicWebview")
public class AcademicWebviewPlugin extends Plugin {

    private Dialog currentDialog = null;
    private WebView currentWebView = null;
    private PluginCall savedCall = null;

    private TextView createCircleIconButton(Context context, String text, float sizeSp, int textColor, int density) {
        TextView btn = new TextView(context);
        btn.setText(text);
        btn.setTextColor(textColor);
        btn.setTextSize(sizeSp);
        btn.setGravity(Gravity.CENTER);
        btn.setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL));
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(34 * density, 34 * density);
        btn.setLayoutParams(params);

        GradientDrawable bg = new GradientDrawable();
        bg.setShape(GradientDrawable.OVAL);
        bg.setColor(Color.parseColor("#f1f5f9"));
        bg.setStroke(1 * density, Color.parseColor("#e2e8f0"));
        btn.setBackground(bg);
        return btn;
    }

    @PluginMethod
    public void open(PluginCall call) {
        String url = call.getString("url", "https://tls.ccsut.cn/admin/login");
        String title = call.getString("title", "长沙工业学院教务系统");

        getActivity().runOnUiThread(() -> {
            try {
                if (currentDialog != null && currentDialog.isShowing()) {
                    currentDialog.dismiss();
                }
                savedCall = call;

                Dialog dialog = new Dialog(getActivity(), android.R.style.Theme_Light_NoTitleBar_Fullscreen);
                currentDialog = dialog;

                Window window = dialog.getWindow();
                if (window != null) {
                    window.setLayout(WindowManager.LayoutParams.MATCH_PARENT, WindowManager.LayoutParams.MATCH_PARENT);
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
                        window.clearFlags(WindowManager.LayoutParams.FLAG_TRANSLUCENT_STATUS);
                        window.addFlags(WindowManager.LayoutParams.FLAG_DRAWS_SYSTEM_BAR_BACKGROUNDS);
                        window.setStatusBarColor(Color.WHITE);
                    }
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                        View decor = window.getDecorView();
                        decor.setSystemUiVisibility(View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR);
                    }
                }

                int density = (int) getActivity().getResources().getDisplayMetrics().density;
                if (density <= 0) density = 1;

                int statusBarHeight = 0;
                int resId = getActivity().getResources().getIdentifier("status_bar_height", "dimen", "android");
                if (resId > 0) {
                    statusBarHeight = getActivity().getResources().getDimensionPixelSize(resId);
                }
                if (statusBarHeight <= 0) {
                    statusBarHeight = 24 * density;
                }

                // 根布局：极简浅色画布背景
                LinearLayout root = new LinearLayout(getActivity());
                root.setOrientation(LinearLayout.VERTICAL);
                root.setBackgroundColor(Color.parseColor("#f8fafc"));
                root.setLayoutParams(new ViewGroup.LayoutParams(
                        ViewGroup.LayoutParams.MATCH_PARENT,
                        ViewGroup.LayoutParams.MATCH_PARENT
                ));

                // 顶部导航栏：纯净白底、自适应状态栏高度内边距
                LinearLayout header = new LinearLayout(getActivity());
                header.setOrientation(LinearLayout.HORIZONTAL);
                header.setBackgroundColor(Color.WHITE);
                header.setGravity(Gravity.CENTER_VERTICAL);
                header.setPadding(12 * density, statusBarHeight + 6 * density, 12 * density, 10 * density);
                header.setLayoutParams(new LinearLayout.LayoutParams(
                        ViewGroup.LayoutParams.MATCH_PARENT,
                        ViewGroup.LayoutParams.WRAP_CONTENT
                ));

                // 控制按钮组：圆润极简 Slate 灰胶囊微按钮
                LinearLayout btnGroup = new LinearLayout(getActivity());
                btnGroup.setOrientation(LinearLayout.HORIZONTAL);
                btnGroup.setGravity(Gravity.CENTER_VERTICAL);

                // 关闭按钮 [✕]
                TextView btnClose = createCircleIconButton(getActivity(), "✕", 13.5f, Color.parseColor("#334155"), density);
                btnGroup.addView(btnClose);

                // 后退按钮 [‹]
                TextView btnBack = createCircleIconButton(getActivity(), "‹", 22f, Color.parseColor("#475569"), density);
                LinearLayout.LayoutParams backParams = (LinearLayout.LayoutParams) btnBack.getLayoutParams();
                backParams.setMargins(6 * density, 0, 0, 0);
                btnBack.setLayoutParams(backParams);
                btnGroup.addView(btnBack);

                // 刷新按钮 [↻]
                TextView btnRefresh = createCircleIconButton(getActivity(), "↻", 15f, Color.parseColor("#64748b"), density);
                LinearLayout.LayoutParams refreshParams = (LinearLayout.LayoutParams) btnRefresh.getLayoutParams();
                refreshParams.setMargins(6 * density, 0, 0, 0);
                btnRefresh.setLayoutParams(refreshParams);
                btnGroup.addView(btnRefresh);

                header.addView(btnGroup);

                // 标题与域名副标容器
                LinearLayout titleBox = new LinearLayout(getActivity());
                titleBox.setOrientation(LinearLayout.VERTICAL);
                titleBox.setGravity(Gravity.CENTER_VERTICAL);
                LinearLayout.LayoutParams titleBoxParams = new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1.0f);
                titleBoxParams.setMargins(10 * density, 0, 10 * density, 0);
                titleBox.setLayoutParams(titleBoxParams);

                TextView tvTitle = new TextView(getActivity());
                tvTitle.setText(title);
                tvTitle.setTextColor(Color.parseColor("#0f172a"));
                tvTitle.setTextSize(14.5f);
                tvTitle.setTypeface(Typeface.DEFAULT_BOLD);
                tvTitle.setSingleLine(true);
                tvTitle.setEllipsize(android.text.TextUtils.TruncateAt.END);
                titleBox.addView(tvTitle);

                TextView tvSubtitle = new TextView(getActivity());
                tvSubtitle.setText("tls.ccsut.cn · 强智教务系统");
                tvSubtitle.setTextColor(Color.parseColor("#94a3b8"));
                tvSubtitle.setTextSize(10.5f);
                tvSubtitle.setSingleLine(true);
                tvSubtitle.setEllipsize(android.text.TextUtils.TruncateAt.END);
                titleBox.addView(tvSubtitle);

                header.addView(titleBox);

                // 一键导入课表按钮（极简深邃石墨黑高质感胶囊按钮）
                Button btnImport = new Button(getActivity());
                btnImport.setText("一键导入");
                btnImport.setTextColor(Color.WHITE);
                btnImport.setTextSize(12.5f);
                btnImport.setTypeface(Typeface.DEFAULT_BOLD);
                btnImport.setAllCaps(false);
                btnImport.setGravity(Gravity.CENTER);

                LinearLayout.LayoutParams btnImportParams = new LinearLayout.LayoutParams(
                        ViewGroup.LayoutParams.WRAP_CONTENT,
                        34 * density
                );
                btnImport.setLayoutParams(btnImportParams);
                btnImport.setPadding(14 * density, 0, 14 * density, 0);

                GradientDrawable btnBg = new GradientDrawable();
                btnBg.setColor(Color.parseColor("#0f172a"));
                btnBg.setCornerRadius(17 * density);
                btnImport.setBackground(btnBg);
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
                    btnImport.setElevation(2 * density);
                    btnImport.setStateListAnimator(null);
                }
                header.addView(btnImport);

                root.addView(header);

                // 极简微细分割线 (1px hairline)
                View headerDivider = new View(getActivity());
                headerDivider.setLayoutParams(new LinearLayout.LayoutParams(
                        ViewGroup.LayoutParams.MATCH_PARENT,
                        Math.max(1, density / 2)
                ));
                headerDivider.setBackgroundColor(Color.parseColor("#e2e8f0"));
                root.addView(headerDivider);

                // 网页加载进度条（细微黑灰极简指示）
                ProgressBar progressBar = new ProgressBar(getActivity(), null, android.R.attr.progressBarStyleHorizontal);
                progressBar.setLayoutParams(new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 2 * density));
                progressBar.setMax(100);
                progressBar.setProgress(0);
                if (progressBar.getProgressDrawable() != null) {
                    progressBar.getProgressDrawable().setColorFilter(Color.parseColor("#0f172a"), PorterDuff.Mode.SRC_IN);
                }
                root.addView(progressBar);

                // 操作指引悬浮轻量提示胶囊
                LinearLayout tipBar = new LinearLayout(getActivity());
                tipBar.setOrientation(LinearLayout.HORIZONTAL);
                tipBar.setGravity(Gravity.CENTER_VERTICAL);
                LinearLayout.LayoutParams tipParams = new LinearLayout.LayoutParams(
                        ViewGroup.LayoutParams.MATCH_PARENT,
                        ViewGroup.LayoutParams.WRAP_CONTENT
                );
                tipParams.setMargins(12 * density, 6 * density, 12 * density, 6 * density);
                tipBar.setLayoutParams(tipParams);

                GradientDrawable tipBg = new GradientDrawable();
                tipBg.setColor(Color.parseColor("#ffffff"));
                tipBg.setStroke(1 * density, Color.parseColor("#e2e8f0"));
                tipBg.setCornerRadius(10 * density);
                tipBar.setBackground(tipBg);
                tipBar.setPadding(10 * density, 7 * density, 10 * density, 7 * density);

                TextView tvTip = new TextView(getActivity());
                tvTip.setText("💡 登录进入【学生课表】页面，待课表完整显示后点击右上角【一键导入】");
                tvTip.setTextColor(Color.parseColor("#475569"));
                tvTip.setTextSize(11f);
                tvTip.setLineSpacing(2 * density, 1.0f);
                tipBar.addView(tvTip);
                root.addView(tipBar);

                // WebView
                WebView webView = new WebView(getActivity());
                currentWebView = webView;
                webView.setBackgroundColor(Color.WHITE);
                LinearLayout.LayoutParams webParams = new LinearLayout.LayoutParams(
                        ViewGroup.LayoutParams.MATCH_PARENT,
                        0,
                        1.0f
                );
                webView.setLayoutParams(webParams);
                root.addView(webView);

                // 配置 WebView 属性
                WebSettings settings = webView.getSettings();
                settings.setJavaScriptEnabled(true);
                settings.setDomStorageEnabled(true);
                settings.setDatabaseEnabled(true);
                settings.setUseWideViewPort(true);
                settings.setLoadWithOverviewMode(true);
                settings.setSupportZoom(true);
                settings.setBuiltInZoomControls(true);
                settings.setDisplayZoomControls(false);
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
                    settings.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
                }

                CookieManager cookieManager = CookieManager.getInstance();
                cookieManager.setAcceptCookie(true);
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
                    cookieManager.setAcceptThirdPartyCookies(webView, true);
                }

                // 注入 JS 桥接接口
                webView.addJavascriptInterface(new Object() {
                    @JavascriptInterface
                    public void onScheduleData(String jsonString) {
                        getActivity().runOnUiThread(() -> {
                            if (savedCall != null) {
                                JSObject ret = new JSObject();
                                ret.put("data", jsonString);
                                savedCall.resolve(ret);
                                savedCall = null;
                            }
                            if (dialog.isShowing()) {
                                dialog.dismiss();
                            }
                        });
                    }
                }, "AcademicBridge");

                // 嗅探脚本：拦截 fetch/XHR 中包含课表字段的响应。
                // aTrust 等零信任网关会在页面脚本之前接管/替换网络 API，因此：
                // 1. 包装必须幂等且可链式叠加——每次 tick 检查当前 send/fetch 是否仍是我们的包装，
                //    被网关替换后在其外层重新包装（委托原实现，不破坏网关逻辑）；
                // 2. 抓到的数据同时写入 window 变量与 localStorage（带 30 分钟时效），
                //    避免登录跳转链路中页面导航导致数据丢失；
                // 3. 兼容 responseType='json' 等 responseText 不可读的情况（回退序列化 response）。
                final String snifferJs = "(function() {" +
                        "  function store(txt) {" +
                        "    try {" +
                        "      if (!txt || txt.length > 3000000) return;" +
                        "      if (txt.indexOf('kcmc') === -1 && txt.indexOf('jxbmc') === -1 && txt.indexOf('croommc') === -1 && txt.indexOf('openKckb') === -1) return;" +
                        "      window.__latestScheduleData = txt;" +
                        "      try { if (window.top) window.top.__latestScheduleData = txt; } catch(e) {}" +
                        "      var env = JSON.stringify({ t: (new Date()).getTime(), d: txt });" +
                        "      try { window.localStorage.setItem('__scheduleCapture', env); } catch(e) {}" +
                        "      try { if (window.top && window.top.localStorage) window.top.localStorage.setItem('__scheduleCapture', env); } catch(e) {}" +
                        "    } catch(e) {}" +
                        "  }" +
                        "  function hookTarget(w) {" +
                        "    if (!w) return;" +
                        "    try {" +
                        "      var proto = w.XMLHttpRequest && w.XMLHttpRequest.prototype;" +
                        "      if (proto && proto.send !== w.__scheduleWrappedSend) {" +
                        "        var origSend = proto.send;" +
                        "        var wrappedSend = function() {" +
                        "          var xhr = this;" +
                        "          try {" +
                        "            xhr.addEventListener('load', function() {" +
                        "              try {" +
                        "                var txt = '';" +
                        "                try { txt = xhr.responseText; } catch(e) {" +
                        "                  try { var r = xhr.response; txt = (typeof r === 'string') ? r : (r == null ? '' : JSON.stringify(r)); } catch(e2) {}" +
                        "                }" +
                        "                store(txt);" +
                        "              } catch(e) {}" +
                        "            });" +
                        "          } catch(e) {}" +
                        "          return origSend.apply(this, arguments);" +
                        "        };" +
                        "        proto.send = wrappedSend;" +
                        "        w.__scheduleWrappedSend = wrappedSend;" +
                        "      }" +
                        "      if (typeof w.fetch === 'function' && w.fetch !== w.__scheduleWrappedFetch) {" +
                        "        var origFetch = w.fetch;" +
                        "        var wrappedFetch = function() {" +
                        "          var args = arguments;" +
                        "          var p = origFetch.apply(this, args);" +
                        "          try {" +
                        "            if (p && p.then) {" +
                        "              p.then(function(res) {" +
                        "                try { if (res && res.clone) res.clone().text().then(store).catch(function(){}); } catch(e) {}" +
                        "              }).catch(function(){});" +
                        "            }" +
                        "          } catch(e) {}" +
                        "          return p;" +
                        "        };" +
                        "        w.fetch = wrappedFetch;" +
                        "        w.__scheduleWrappedFetch = wrappedFetch;" +
                        "      }" +
                        "    } catch(e) {}" +
                        "  }" +
                        "  function hookAll(root) {" +
                        "    if (!root) return;" +
                        "    hookTarget(root);" +
                        "    try {" +
                        "      for (var i = 0; i < root.frames.length; i++) {" +
                        "        hookAll(root.frames[i]);" +
                        "      }" +
                        "    } catch(e) {}" +
                        "  }" +
                        "  hookAll(window);" +
                        "  if (!window.__hookTimer) {" +
                        "    window.__hookTimer = setInterval(function() { hookAll(window); }, 300);" +
                        "  }" +
                        "})();";

                // document-start 注入：确保嗅探脚本先于页面与网关（aTrust）注入的一切脚本执行。
                // evaluateJavascript 注入仅在主 frame 且时机偏晚，是此前手机端抓不到课表 JSON 的主因。
                try {
                    if (WebViewFeature.isFeatureSupported(WebViewFeature.DOCUMENT_START_SCRIPT)) {
                        java.util.Set<String> origins = new java.util.HashSet<>();
                        origins.add("https://tls.ccsut.cn");
                        origins.add("https://zts.ccsut.cn");
                        try {
                            Uri launchUri = Uri.parse(url);
                            String scheme = launchUri.getScheme() != null ? launchUri.getScheme() : "https";
                            String host = launchUri.getHost();
                            if (host != null && !host.isEmpty()) {
                                origins.add(scheme + "://" + host);
                            }
                        } catch (Exception ignored) {}
                        WebViewCompat.addDocumentStartJavaScript(webView, snifferJs, origins);
                    }
                } catch (Exception ignored) {}

                // WebViewClient 处理跳转与 SSL
                webView.setWebViewClient(new WebViewClient() {
                    @Override
                    public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                        String reqUrl = request.getUrl().toString();
                        if (reqUrl.startsWith("http://") || reqUrl.startsWith("https://")) {
                            return false;
                        }
                        return true;
                    }

                    @Override
                    public void onReceivedSslError(WebView view, SslErrorHandler handler, SslError error) {
                        // 校园网及 VPN 内部网关常使用自签名或内部 CA 证书，避免被系统拦截
                        handler.proceed();
                    }

                    @Override
                    public void onPageStarted(WebView view, String url, android.graphics.Bitmap favicon) {
                        super.onPageStarted(view, url, favicon);
                        view.evaluateJavascript(snifferJs, null);
                    }

                    @Override
                    public void onPageFinished(WebView view, String finishedUrl) {
                        super.onPageFinished(view, finishedUrl);
                        view.evaluateJavascript(snifferJs, null);
                        try {
                            Uri uri = Uri.parse(finishedUrl);
                            if (uri != null && uri.getHost() != null) {
                                tvSubtitle.setText(uri.getHost() + " · 强智教务系统");
                            }
                        } catch (Exception ignored) {}
                    }
                });

                // WebChromeClient 进度条与标题
                webView.setWebChromeClient(new WebChromeClient() {
                    @Override
                    public void onProgressChanged(WebView view, int newProgress) {
                        progressBar.setProgress(newProgress);
                        if (newProgress >= 100) {
                            progressBar.setVisibility(View.GONE);
                        } else {
                            progressBar.setVisibility(View.VISIBLE);
                        }
                        view.evaluateJavascript(snifferJs, null);
                    }

                    @Override
                    public void onReceivedTitle(WebView view, String pageTitle) {
                        if (pageTitle != null && !pageTitle.isEmpty()
                                && !pageTitle.contains("Loading")
                                && !pageTitle.contains("Webpage not available")
                                && !pageTitle.contains("404")
                                && !pageTitle.contains("Error")) {
                            tvTitle.setText(pageTitle);
                        }
                    }
                });

                // 控制按钮点击事件
                btnClose.setOnClickListener(v -> {
                    if (savedCall != null) {
                        JSObject ret = new JSObject();
                        ret.put("cancelled", true);
                        savedCall.resolve(ret);
                        savedCall = null;
                    }
                    dialog.dismiss();
                });

                btnBack.setOnClickListener(v -> {
                    if (webView.canGoBack()) {
                        webView.goBack();
                    } else {
                        Toast.makeText(getActivity(), "已经是第一页了", Toast.LENGTH_SHORT).show();
                    }
                });

                btnRefresh.setOnClickListener(v -> webView.reload());

                // 点击【一键导入课表】优先提取缓存的 JSON 课表，若无则检查脚本标签与整个网页的表格与 frame 内容
                btnImport.setOnClickListener(v -> {
                    btnImport.setEnabled(false);
                    btnImport.setText("正在提取…");
                    Toast.makeText(getActivity(), "正在提取页面课表，请稍候…", Toast.LENGTH_SHORT).show();

                    String js = "(function() {" +
                            "  function readCapture(win) {" +
                            "    try { if (win.__latestScheduleData) return win.__latestScheduleData; } catch(e) {}" +
                            "    try {" +
                            "      var raw = win.localStorage && win.localStorage.getItem('__scheduleCapture');" +
                            "      if (raw) {" +
                            "        var env = JSON.parse(raw);" +
                            "        if (env && env.d && (new Date()).getTime() - env.t < 1800000) return env.d;" +
                            "      }" +
                            "    } catch(e) {}" +
                            "    return null;" +
                            "  }" +
                            "  function findLatestData(win, depth) {" +
                            "    if (!win || depth > 8) return null;" +
                            "    var hit = readCapture(win);" +
                            "    if (hit) return hit;" +
                            "    try {" +
                            "      for (var f = 0; f < win.frames.length; f++) {" +
                            "        var sub = findLatestData(win.frames[f], depth + 1);" +
                            "        if (sub) return sub;" +
                            "      }" +
                            "    } catch(e) {}" +
                            "    return null;" +
                            "  }" +
                            "  var found = findLatestData(window, 0);" +
                            "  if (found) {" +
                            "    window.AcademicBridge.onScheduleData(found);" +
                            "    return;" +
                            "  }" +
                            "  function scanScripts(win, depth) {" +
                            "    if (!win || depth > 8) return null;" +
                            "    try {" +
                            "      var scripts = win.document.querySelectorAll('script');" +
                            "      for (var i = 0; i < scripts.length; i++) {" +
                            "        var txt = scripts[i].textContent || scripts[i].innerText || '';" +
                            "        if (txt && (txt.indexOf('kcmc') !== -1 || txt.indexOf('jxbmc') !== -1) && (txt.indexOf('\"data\"') !== -1 || txt.indexOf('\"courses\"') !== -1)) {" +
                            "          var m = txt.match(/(\\{[\\s\\S]*\"(kcmc|jxbmc)\"[\\s\\S]*\\}|\\[[\\s\\S]*\"(kcmc|jxbmc)\"[\\s\\S]*\\])/);" +
                            "          if (m) return m[1];" +
                            "        }" +
                            "      }" +
                            "      for (var f = 0; f < win.frames.length; f++) {" +
                            "        var sub = scanScripts(win.frames[f], depth + 1);" +
                            "        if (sub) return sub;" +
                            "      }" +
                            "    } catch(e) {}" +
                            "    return null;" +
                            "  }" +
                            "  var scriptData = scanScripts(window, 0);" +
                            "  if (scriptData) {" +
                            "    window.AcademicBridge.onScheduleData(scriptData);" +
                            "    return;" +
                            "  }" +
                            "  function extract(win, depth) {" +
                            "    if (depth > 6) return [];" +
                            "    var res = [];" +
                            "    try {" +
                            "      var doc = win.document;" +
                            "      if (doc) {" +
                            "        var clone = doc.documentElement.cloneNode(true);" +
                            "        var toRemove = clone.querySelectorAll('script, style, svg, noscript, link[rel=\"stylesheet\"]');" +
                            "        for (var i = 0; i < toRemove.length; i++) {" +
                            "          if (toRemove[i].parentNode) toRemove[i].parentNode.removeChild(toRemove[i]);" +
                            "        }" +
                            "        var tables = clone.querySelectorAll('table');" +
                            "        var tablesHtml = '';" +
                            "        for (var j = 0; j < tables.length; j++) {" +
                            "          tablesHtml += tables[j].outerHTML + '\\n';" +
                            "        }" +
                            "        res.push({" +
                            "          url: win.location.href || ''," +
                            "          title: doc.title || ''," +
                            "          text: doc.body ? doc.body.innerText : ''," +
                            "          tablesHtml: tablesHtml," +
                            "          html: clone.outerHTML" +
                            "        });" +
                            "      }" +
                            "      var frames = win.frames;" +
                            "      for (var f = 0; f < frames.length; f++) {" +
                            "        res = res.concat(extract(frames[f], depth + 1));" +
                            "      }" +
                            "    } catch(e) {}" +
                            "    return res;" +
                            "  }" +
                            "  var data = extract(window, 0);" +
                            "  window.AcademicBridge.onScheduleData(JSON.stringify(data));" +
                            "})();";

                    webView.evaluateJavascript(js, null);

                    webView.postDelayed(() -> {
                        btnImport.setEnabled(true);
                        btnImport.setText("一键导入");
                    }, 4000);
                });

                // 物理返回键处理
                dialog.setOnKeyListener((dialogInterface, keyCode, event) -> {
                    if (keyCode == KeyEvent.KEYCODE_BACK && event.getAction() == KeyEvent.ACTION_UP) {
                        if (webView.canGoBack()) {
                            webView.goBack();
                            return true;
                        } else {
                            if (savedCall != null) {
                                JSObject ret = new JSObject();
                                ret.put("cancelled", true);
                                savedCall.resolve(ret);
                                savedCall = null;
                            }
                            dialog.dismiss();
                            return true;
                        }
                    }
                    return false;
                });

                dialog.setOnDismissListener(dialogInterface -> {
                    if (savedCall != null) {
                        JSObject ret = new JSObject();
                        ret.put("cancelled", true);
                        savedCall.resolve(ret);
                        savedCall = null;
                    }
                    if (currentWebView != null) {
                        currentWebView.stopLoading();
                        currentWebView.destroy();
                        currentWebView = null;
                    }
                    currentDialog = null;
                });

                dialog.setContentView(root);
                webView.loadUrl(url);
                dialog.show();

            } catch (Exception e) {
                call.reject("无法打开教务系统 WebView: " + e.getMessage(), e);
            }
        });
    }
}
