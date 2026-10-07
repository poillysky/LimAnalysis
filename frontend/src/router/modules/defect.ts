const Layout = () => import("@/layout/index.vue");

export default {
  path: "/defect",
  name: "Defect",
  component: Layout,
  redirect: "/defect/analysis",
  meta: {
    icon: "ri/notification-3-fill",
    title: "通知中心",
    rank: 1
  },
  children: [
    {
      path: "/defect/analysis",
      name: "DefectAnalysis",
      component: () => import("@/views/defect/analysis/index.vue"),
      meta: {
        title: "系统通知",
        icon: "ri/alarm-warning-line"
      }
    },
    {
      path: "/defect/manual",
      name: "DefectManual",
      component: () => import("@/views/defect/manual/index.vue"),
      meta: {
        title: "人工通知",
        icon: "ri/chat-1-line"
      }
    }
  ]
} satisfies RouteConfigsTable;
