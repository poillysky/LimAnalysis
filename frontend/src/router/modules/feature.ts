const Layout = () => import("@/layout/index.vue");

export default {
  path: "/feature",
  name: "Feature",
  component: Layout,
  redirect: "/feature/users",
  meta: {
    icon: "ri/settings-3-fill",
    title: "功能管理",
    rank: 10
  },
  children: [
    {
      path: "/feature/users",
      name: "FeatureUsers",
      component: () => import("@/views/feature/users.vue"),
      meta: {
        title: "用户管理",
        icon: "ri/user-3-line"
      }
    },
    {
      path: "/feature/persons",
      name: "FeaturePersons",
      component: () => import("@/views/feature/persons.vue"),
      meta: {
        title: "人员管理",
        icon: "ri/contacts-line"
      }
    },
    {
      path: "/feature/roster",
      name: "FeatureRoster",
      component: () => import("@/views/feature/roster.vue"),
      meta: {
        title: "排班表",
        icon: "ri/calendar-schedule-line"
      }
    },
    {
      path: "/feature/index",
      name: "FeatureIndex",
      component: () => import("@/views/feature/index.vue"),
      meta: {
        title: "项目管理",
        icon: "ri/folder-open-line"
      }
    },
    {
      path: "/feature/connections",
      name: "FeatureConnections",
      component: () => import("@/views/feature/connections.vue"),
      meta: {
        title: "外部连接",
        icon: "ri/link"
      }
    },
    {
      path: "/feature/db-browser",
      name: "FeatureDbBrowser",
      component: () => import("@/views/feature/db-browser.vue"),
      meta: {
        title: "数据浏览",
        icon: "ri/database-2-line"
      }
    },
    {
      path: "/feature/sfc",
      name: "FeatureSfc",
      component: () => import("@/views/feature/sfc.vue"),
      meta: {
        title: "SFC爬虫",
        icon: "ri/focus-3-line"
      }
    },
    {
      path: "/feature/etl",
      name: "FeatureEtl",
      component: () => import("@/views/feature/etl.vue"),
      meta: {
        title: "数据清洗",
        icon: "ri/brush-line"
      }
    },
    {
      path: "/feature/agg",
      name: "FeatureAgg",
      component: () => import("@/views/feature/agg.vue"),
      meta: {
        title: "数据聚合",
        icon: "ri/pie-chart-line"
      }
    },
    {
      path: "/feature/inspection",
      name: "FeatureInspection",
      component: () => import("@/views/feature/inspection.vue"),
      meta: {
        title: "图片目录",
        icon: "ri/camera-line"
      }
    },
    {
      path: "/feature/scan-defects",
      name: "FeatureScanDefects",
      component: () => import("@/views/feature/scan-defects.vue"),
      meta: {
        title: "次品名称",
        icon: "ri/list-check-3"
      }
    },
    {
      path: "/feature/ai-model",
      name: "FeatureAiModel",
      component: () => import("@/views/feature/ai-model.vue"),
      meta: {
        title: "AI模型配置",
        icon: "ri/cpu-line"
      }
    }
  ]
} satisfies RouteConfigsTable;
