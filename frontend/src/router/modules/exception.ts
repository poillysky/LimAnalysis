const Layout = () => import("@/layout/index.vue");

export default {
  path: "/exception",
  name: "Exception",
  component: Layout,
  redirect: "/exception/monitor",
  meta: {
    icon: "ri/dashboard-fill",
    title: "数据看板",
    rank: 3
  },
  children: [
    {
      path: "/exception/monitor",
      name: "ExceptionMonitor",
      component: () => import("@/views/exception/monitor/index.vue"),
      meta: {
        title: "自动外观数据看板",
        icon: "ri/dashboard-line"
      }
    },
    {
      path: "/exception/query",
      redirect: "/exception/cavity",
      meta: {
        title: "数据查询",
        showLink: false
      }
    },
    {
      path: "/exception/cavity",
      name: "ExceptionCavity",
      component: () => import("@/views/exception/cavity/index.vue"),
      meta: {
        title: "自动外观数据分析",
        icon: "ri/grid-line"
      }
    }
  ]
} satisfies RouteConfigsTable;
