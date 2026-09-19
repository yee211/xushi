/**
 * 功能开关：仅控制入口显示，相关组件、路由与业务逻辑全部保留。
 * 需要恢复某功能时把对应值改回 true 即可。
 */
export const FEATURES = {
  /** 添加课程（手动新建课程） */
  addCourse: false,
  /** 调课中心（变更记录 / 图片识别调课 / 单周微调入口） */
  adjustmentCenter: false,
}
