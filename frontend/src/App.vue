<template>
  <el-config-provider :locale="currentLocale">
    <router-view />
    <ReDialog />
  </el-config-provider>
</template>

<script lang="ts">
import { defineComponent } from "vue";
import { ReDialog } from "@/components/ReDialog";
import zhCn from "element-plus/es/locale/lang/zh-cn";

// ElConfigProvider 已在 plugins/elementPlus.ts 的 components 列表里全局注册
// （useElementPlus → app.component），这里不需要再局部注册一次。
// 原写法 `[ElConfigProvider.name]: ElConfigProvider` 有两个问题：
//   1. strict 下报 TS2464 —— ElConfigProvider.name 在其类型声明里是
//      `string | undefined`，不能拿来做计算属性名；
//   2. 即便不报，也是重复注册，属于无效代码。
export default defineComponent({
  name: "app",
  components: {
    ReDialog
  },
  computed: {
    currentLocale() {
      return zhCn;
    }
  }
});
</script>
