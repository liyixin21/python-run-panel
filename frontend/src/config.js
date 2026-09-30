/**
 * 应用级可配置元信息。
 * 这些值原本硬编码在各个组件里，部署给他人使用时不便修改。
 * 可通过构建时的环境变量覆盖（Vite 会替换 import.meta.env.VITE_*）。
 */

export const APP_TITLE = import.meta.env.VITE_APP_TITLE || 'Python Run Panel'
export const APP_SUBTITLE = import.meta.env.VITE_APP_SUBTITLE || '项目管理面板'

// 页脚署名，留空则不显示对应入口
export const FOOTER_AUTHOR_NAME = import.meta.env.VITE_FOOTER_AUTHOR_NAME ?? 'liyixin'
export const FOOTER_AUTHOR_URL = import.meta.env.VITE_FOOTER_AUTHOR_URL ?? 'https://liyixin.vip'
export const FOOTER_PROJECT_URL =
  import.meta.env.VITE_FOOTER_PROJECT_URL ?? 'https://github.com/liyixin21/python-run-panel'

export default {
  APP_TITLE,
  APP_SUBTITLE,
  FOOTER_AUTHOR_NAME,
  FOOTER_AUTHOR_URL,
  FOOTER_PROJECT_URL,
}
