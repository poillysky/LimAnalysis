/**
 * Vite 资源导入的类型声明。
 *
 * `vite-svg-loader` 的三种查询后缀（见 node_modules/vite-svg-loader/index.js）：
 *   - `?raw`      → `export default "<svg 源码字符串>"`
 *   - `?component` → 走 compileTemplate，导出 `{ render }`，即一个 Vue 组件 options 对象
 *   - 无后缀 / `?url` → 走 Vite 默认资源管线，导出 URL 字符串
 *
 * ⚠️ 以前这里什么都没声明。strict: false 时 TS 静默放过，strict 打开后
 * `import noAccess from "@/assets/status/403.svg?component"` 立刻报 TS2307。
 * 声明类型要与 loader 真实导出对齐，不要图省神写成 `any`。
 */

declare module "*.svg?component" {
  import type { ComponentOptions } from "vue";
  /** vite-svg-loader 实际导出的是 `{ render }`，等价于一个函数式组件的 options */
  const component: ComponentOptions;
  export default component;
}

declare module "*.svg?raw" {
  const raw: string;
  export default raw;
}

declare module "*.svg" {
  const url: string;
  export default url;
}
