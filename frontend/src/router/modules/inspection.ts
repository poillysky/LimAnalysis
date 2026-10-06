const Layout = () => import("@/layout/index.vue");

export default {
  path: "/inspection",
  name: "Inspection",
  component: Layout,
  redirect: "/inspection/viewer",
  meta: {
    icon: "ri/camera-fill",
    title: "图片查阅",
    rank: 4
  },
  children: [
    {
      path: "/inspection/viewer",
      name: "InspectionViewer",
      component: () => import("@/views/inspection/viewer.vue"),
      meta: {
        title: "注塑机图片",
        icon: "ri/image-line",
        photoSource: "mold"
      }
    },
    {
      path: "/inspection/appearance",
      name: "InspectionAppearance",
      component: () => import("@/views/inspection/viewer.vue"),
      meta: {
        title: "自动外观图片",
        icon: "ri/eye-line",
        photoSource: "appearance"
      }
    }
  ]
} satisfies RouteConfigsTable;
