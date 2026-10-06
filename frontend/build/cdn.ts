import { Plugin as importToCDN } from "vite-plugin-cdn-import";

/**
 * 仅在 VITE_CDN=true 时调用。开发环境不要在模块加载时执行，
 * 否则 pnpm 隔离安装下会因找不到顶层 vue-demi 而起不来。
 */
export function getCdnPlugin() {
  return importToCDN({
    prodUrl: "https://cdn.bootcdn.net/ajax/libs/{name}/{version}/{path}",
    modules: [
      {
        name: "vue",
        var: "Vue",
        path: "vue.global.prod.min.js"
      },
      {
        name: "vue-router",
        var: "VueRouter",
        path: "vue-router.global.min.js"
      },
      {
        name: "vue-demi",
        var: "VueDemi",
        path: "index.iife.min.js"
      },
      {
        name: "pinia",
        var: "Pinia",
        path: "pinia.iife.min.js"
      },
      {
        name: "element-plus",
        var: "ElementPlus",
        path: "index.full.min.js",
        css: "index.min.css"
      },
      {
        name: "axios",
        var: "axios",
        path: "axios.min.js"
      },
      {
        name: "dayjs",
        var: "dayjs",
        path: "dayjs.min.js"
      },
      {
        name: "echarts",
        var: "echarts",
        path: "echarts.min.js"
      }
    ]
  });
}
