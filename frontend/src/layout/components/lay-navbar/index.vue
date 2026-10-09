<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { useNav } from "@/layout/hooks/useNav";
import LaySearch from "../lay-search/index.vue";
import LayNotice from "../lay-notice/index.vue";
import LayNavMix from "../lay-sidebar/NavMix.vue";
import LaySidebarFullScreen from "../lay-sidebar/components/SidebarFullScreen.vue";
import LaySidebarBreadCrumb from "../lay-sidebar/components/SidebarBreadCrumb.vue";
import LaySidebarTopCollapse from "../lay-sidebar/components/SidebarTopCollapse.vue";
import {
  hasNativeInstallPrompt,
  installGuideText,
  onPwaInstallChange,
  promptInstallPwa,
  shouldShowInstallEntry
} from "@/utils/pwa";

import LogoutCircleRLine from "~icons/ri/logout-circle-r-line";
import Setting from "~icons/ri/settings-3-line";
import InstallDesktop from "~icons/ri/download-2-line";

const {
  layout,
  device,
  logout,
  onPanel,
  pureApp,
  username,
  userAvatar,
  avatarsStyle,
  toggleSideBar
} = useNav();

const showInstall = ref(shouldShowInstallEntry());
const nativePrompt = ref(hasNativeInstallPrompt());
let stopInstallWatch: (() => void) | undefined;

const installTitle = computed(() =>
  nativePrompt.value
    ? "安装到 Windows 桌面"
    : "安装到桌面（点击查看步骤）"
);

onMounted(() => {
  stopInstallWatch = onPwaInstallChange(() => {
    showInstall.value = shouldShowInstallEntry();
    nativePrompt.value = hasNativeInstallPrompt();
  });
});

onUnmounted(() => {
  stopInstallWatch?.();
});

async function installDesktop() {
  const result = await promptInstallPwa();
  if (result.ok) {
    ElMessage.success("已安装到桌面，可从开始菜单或桌面打开");
    showInstall.value = false;
    return;
  }
  if (result.reason === "dismissed") return;
  if (result.reason === "standalone") {
    showInstall.value = false;
    return;
  }
  await ElMessageBox.alert(installGuideText(), "安装到桌面", {
    confirmButtonText: "知道了",
    customClass: "pwa-install-guide"
  });
}
</script>

<template>
  <div class="navbar bg-[#fff] shadow-xs shadow-[rgba(0,21,41,0.08)]">
    <LaySidebarTopCollapse
      v-if="device === 'mobile'"
      class="hamburger-container"
      :is-active="pureApp.sidebar.opened"
      @toggleClick="toggleSideBar"
    />

    <LaySidebarBreadCrumb
      v-if="layout !== 'mix' && device !== 'mobile'"
      class="breadcrumb-container"
    />

    <LayNavMix v-if="layout === 'mix'" />

    <div class="navbar-end">
      <button
        v-if="showInstall"
        type="button"
        class="pwa-install navbar-bg-hover"
        :title="installTitle"
        @click="installDesktop"
      >
        <IconifyIconOffline :icon="InstallDesktop" />
        <span>安装到桌面</span>
      </button>

      <div v-if="layout === 'vertical'" class="vertical-header-right">
        <!-- 菜单搜索 -->
        <LaySearch id="header-search" />
        <!-- 全屏 -->
        <LaySidebarFullScreen id="full-screen" />
        <!-- 消息通知 -->
        <LayNotice id="header-notice" />
        <!-- 退出登录 -->
        <el-dropdown trigger="click">
          <span class="el-dropdown-link navbar-bg-hover select-none">
            <img :src="userAvatar" :style="avatarsStyle" />
            <p v-if="username" class="dark:text-white">{{ username }}</p>
          </span>
          <template #dropdown>
            <el-dropdown-menu class="logout">
              <el-dropdown-item @click="logout">
                <IconifyIconOffline
                  :icon="LogoutCircleRLine"
                  style="margin: 5px"
                />
                退出系统
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
        <span
          class="set-icon navbar-bg-hover"
          title="打开系统配置"
          @click="onPanel"
        >
          <IconifyIconOffline :icon="Setting" />
        </span>
      </div>
    </div>
  </div>
</template>

<style lang="scss" scoped>
.navbar {
  display: flex;
  align-items: center;
  width: 100%;
  height: var(--la-chrome-nav);
  overflow: hidden;
  background: var(--la-surface-sunken);
  border-bottom: 1px solid var(--la-border-subtle);
  box-sizing: border-box;

  .hamburger-container {
    flex: none;
    height: 100%;
    line-height: var(--la-chrome-nav);
    cursor: pointer;
  }

  .navbar-end {
    display: flex;
    flex: 1 1 auto;
    align-items: center;
    justify-content: flex-end;
    gap: 2px;
    min-width: 0;
    height: var(--la-chrome-nav);
    margin-left: auto;
  }

  .pwa-install {
    display: inline-flex;
    flex: none;
    align-items: center;
    gap: 4px;
    height: 28px;
    padding: 0 8px;
    border: 0;
    border-radius: var(--la-radius-sm);
    background: color-mix(in srgb, var(--el-color-primary) 10%, transparent);
    color: var(--el-color-primary);
    font-size: var(--la-text-xs);
    font-weight: 600;
    cursor: pointer;
    white-space: nowrap;
  }

  .pwa-install:hover {
    background: color-mix(in srgb, var(--el-color-primary) 16%, transparent);
  }

  .vertical-header-right {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    min-width: 0;
    height: var(--la-chrome-nav);
    color: #000000d9;

    .el-dropdown-link {
      display: flex;
      align-items: center;
      justify-content: space-around;
      height: var(--la-chrome-nav);
      padding: 6px 8px;
      color: #000000d9;
      cursor: pointer;

      p {
        font-size: var(--la-text-xs);
      }

      img {
        width: 20px;
        height: 20px;
        border-radius: 50%;
      }
    }
  }

  .breadcrumb-container {
    flex: none;
    margin-left: 12px;
  }
}

.logout {
  width: 120px;

  ::v-deep(.el-dropdown-menu__item) {
    display: inline-flex;
    flex-wrap: wrap;
    min-width: 100%;
  }
}
</style>
