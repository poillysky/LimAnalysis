const Layout = () => import("@/layout/index.vue");

export default {
  path: "/scan",
  name: "ScanAnalysis",
  component: Layout,
  redirect: "/scan/defect",
  meta: {
    icon: "ri/qr-scan-2-line",
    title: "扫码分析",
    rank: 5
  },
  children: [
    {
      path: "/scan/defect",
      name: "ScanDefect",
      component: () => import("@/views/scan/defect.vue"),
      meta: {
        title: "次品扫码",
        icon: "ri/barcode-line"
      }
    },
    {
      path: "/scan/analysis",
      name: "ScanDefectAnalysis",
      component: () => import("@/views/scan/analysis.vue"),
      meta: {
        title: "次品分析",
        icon: "ri/grid-line"
      }
    }
  ]
} satisfies RouteConfigsTable;
