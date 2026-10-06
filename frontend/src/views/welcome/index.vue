<script setup lang="ts">
import { useRouter } from "vue-router";
import { useRenderIcon } from "@/components/ReIcon/src/hooks";

defineOptions({
  name: "Welcome"
});

const router = useRouter();

const entries = [
  {
    title: "数据看板",
    desc: "车间实时异常与处置入口",
    path: "/exception/monitor",
    icon: "ri/dashboard-fill"
  },
  {
    title: "通知中心",
    desc: "系统预警与人工通知",
    path: "/defect/analysis",
    icon: "ri/notification-3-fill"
  },
  {
    title: "注塑机图片",
    desc: "按项目、机台、穴位、日期查看照片",
    path: "/inspection/viewer",
    icon: "ri/image-line"
  },
  {
    title: "SFC 爬虫",
    desc: "配置、日志、拓扑与数据上传",
    path: "/feature/sfc",
    icon: "ri/focus-3-line"
  }
];
</script>

<template>
  <div class="welcome">
    <header class="welcome__head">
      <h1>LimAnalysis</h1>
      <p>车间异常监控 / 通知中心 / 注塑机图片</p>
    </header>

    <div class="welcome__grid">
      <button
        v-for="item in entries"
        :key="item.path"
        type="button"
        class="welcome__card"
        @click="router.push(item.path)"
      >
        <span class="welcome__icon">
          <component :is="useRenderIcon(item.icon)" />
        </span>
        <span class="welcome__title">{{ item.title }}</span>
        <span class="welcome__desc">{{ item.desc }}</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.welcome {
  box-sizing: border-box;
  min-height: calc(100vh - 96px);
  padding: 28px 32px 40px;
  background:
    radial-gradient(
      1200px 480px at 12% -10%,
      rgb(64 158 255 / 12%),
      transparent 55%
    ),
    linear-gradient(180deg, #f7f9fc 0%, #eef2f7 100%);
}

.welcome__head {
  margin-bottom: 28px;
}

.welcome__head h1 {
  margin: 0;
  font-size: 28px;
  font-weight: 700;
  letter-spacing: 0.02em;
  color: #1f2a37;
}

.welcome__head p {
  margin: 8px 0 0;
  font-size: 14px;
  color: #6b7280;
}

.welcome__grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 16px;
  max-width: 960px;
}

.welcome__card {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 6px;
  padding: 18px 18px 16px;
  text-align: left;
  cursor: pointer;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  transition:
    border-color 0.2s ease,
    box-shadow 0.2s ease,
    transform 0.2s ease;
}

.welcome__card:hover {
  border-color: #93c5fd;
  box-shadow: 0 8px 24px rgb(15 23 42 / 6%);
  transform: translateY(-2px);
}

.welcome__icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  margin-bottom: 4px;
  font-size: 20px;
  color: #2563eb;
  background: #eff6ff;
  border-radius: 8px;
}

.welcome__title {
  font-size: 16px;
  font-weight: 600;
  color: #111827;
}

.welcome__desc {
  font-size: 13px;
  line-height: 1.45;
  color: #6b7280;
}
</style>
