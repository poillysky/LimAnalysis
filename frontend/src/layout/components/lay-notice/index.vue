<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import {
  getYieldAlerts,
  listManualNotices,
  type ManualNotice,
  type YieldAlertRow,
  type YieldNotice
} from "@/api/modules/defect";
import type { ListItem, TabItem } from "./data";
import NoticeList from "./components/NoticeList.vue";
import BellIcon from "~icons/ep/bell";

const POLL_MS = 60_000;
const MANUAL_KEEP = 20;

const notices = ref<TabItem[]>(emptyTabs());
const activeKey = ref("system");
let pollTimer: ReturnType<typeof setInterval> | null = null;
let loadAbort: AbortController | null = null;

const noticesNum = computed(() =>
  notices.value.reduce((sum, tab) => sum + tab.list.length, 0)
);

const getLabel = computed(
  () => (item: TabItem) =>
    item.name + (item.list.length > 0 ? `(${item.list.length})` : "")
);

function emptyTabs(): TabItem[] {
  return [
    {
      key: "system",
      name: "系统通知",
      list: [],
      emptyText: "近 3 小时没有待通知人员"
    },
    {
      key: "manual",
      name: "人工通知",
      list: [],
      emptyText: "还没有发出过通知"
    }
  ];
}

function isAbortError(error: unknown) {
  return (
    (error as { code?: string; name?: string })?.code === "ERR_CANCELED" ||
    (error as { name?: string })?.name === "CanceledError" ||
    (error as { name?: string })?.name === "AbortError"
  );
}

function rateText(value: number | null | undefined) {
  return value == null ? "—" : `${Number(value).toFixed(2)}%`;
}

function windowLabel(fromHour: string, toHour: string) {
  if (fromHour && toHour && fromHour !== toHour) return `${fromHour} ~ ${toHour}`;
  return fromHour || toHour || "近 3 小时";
}

function machineNames(item: YieldNotice) {
  const seen = new Set<string>();
  const names: string[] = [];
  for (const row of item.machines) {
    const label = row.project_name
      ? `${row.project_name} ${row.machine}`
      : row.machine;
    if (seen.has(label)) continue;
    seen.add(label);
    names.push(label);
  }
  return names;
}

function mapYieldNotices(
  items: YieldNotice[],
  duty: string,
  fromHour: string,
  toHour: string
): ListItem[] {
  const when = windowLabel(fromHour, toHour);
  return items.map(item => {
    const machines = machineNames(item);
    return {
      title: `${item.name}${item.phone ? ` ${item.phone}` : ""}`,
      description: `${duty || "当前班次"} · ${machines.join("、") || "机台"} 不良率超标`,
      datetime: when,
      extra: "待通知",
      status: "danger",
      type: "system",
      path: "/defect/analysis"
    };
  });
}

function mapUnassignedAlerts(
  alerts: YieldAlertRow[],
  duty: string,
  fromHour: string,
  toHour: string
): ListItem[] {
  const when = windowLabel(fromHour, toHour);
  const seen = new Set<string>();
  const list: ListItem[] = [];
  for (const row of alerts) {
    if (row.contacts.length) continue;
    const key = `${row.project_id || ""}:${row.machine}`;
    if (seen.has(key)) continue;
    seen.add(key);
    const name = row.project_name
      ? `${row.project_name} ${row.machine}`
      : row.machine;
    list.push({
      title: name,
      description: `${duty || "当前班次"} · 机台不良率 ${rateText(
        row.machine_rate_pct ?? row.rate_pct
      )}，未排到人`,
      datetime: when,
      extra: "未排班",
      status: "warning",
      type: "system",
      path: "/defect/analysis"
    });
  }
  return list;
}

function mapManual(items: ManualNotice[]): ListItem[] {
  return items.slice(0, MANUAL_KEEP).map(item => {
    const people = item.recipients
      .map(row => row.name || row.department)
      .filter(Boolean)
      .join("、");
    return {
      title: item.topic || "部门沟通",
      description: people
        ? `${item.from_dept ? `${item.from_dept} → ` : ""}${people}${
            item.body ? ` · ${item.body}` : ""
          }`
        : item.body || "人工通知",
      datetime: item.created_at || "",
      extra: "已发出",
      status: "info",
      type: "manual",
      path: "/defect/manual"
    };
  });
}

async function loadNotices() {
  loadAbort?.abort();
  loadAbort = new AbortController();
  const signal = loadAbort.signal;
  try {
    const [yieldRes, manualRes] = await Promise.allSettled([
      getYieldAlerts({ hours: 3 }, signal),
      listManualNotices(signal)
    ]);
    const yieldData =
      yieldRes.status === "fulfilled" ? yieldRes.value?.data : null;
    const manuals =
      manualRes.status === "fulfilled"
        ? manualRes.value?.data?.notices || []
        : [];
    const people = mapYieldNotices(
      yieldData?.notices || [],
      yieldData?.duty || "",
      yieldData?.from_hour || "",
      yieldData?.to_hour || ""
    );
    const unassigned = mapUnassignedAlerts(
      yieldData?.alerts || [],
      yieldData?.duty || "",
      yieldData?.from_hour || "",
      yieldData?.to_hour || ""
    );
    notices.value = [
      {
        key: "system",
        name: "系统通知",
        list: [...people, ...unassigned],
        emptyText: "近 3 小时没有待通知人员"
      },
      {
        key: "manual",
        name: "人工通知",
        list: mapManual(manuals),
        emptyText: "还没有发出过通知"
      }
    ];
    if (!notices.value.some(tab => tab.key === activeKey.value)) {
      activeKey.value = "system";
    }
  } catch (error) {
    if (!isAbortError(error)) notices.value = emptyTabs();
  }
}

onMounted(() => {
  void loadNotices();
  pollTimer = setInterval(() => {
    void loadNotices();
  }, POLL_MS);
});

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer);
  loadAbort?.abort();
});
</script>

<template>
  <el-dropdown trigger="click" placement="bottom-end" @visible-change="(open: boolean) => open && loadNotices()">
    <span
      :class="[
        'dropdown-badge',
        'navbar-bg-hover',
        'select-none',
        Number(noticesNum) !== 0 && 'mr-[10px]'
      ]"
    >
      <el-badge :value="Number(noticesNum) === 0 ? '' : noticesNum" :max="99">
        <span class="header-notice-icon">
          <IconifyIconOffline :icon="BellIcon" />
        </span>
      </el-badge>
    </span>
    <template #dropdown>
      <el-dropdown-menu>
        <el-tabs
          v-model="activeKey"
          :stretch="true"
          class="dropdown-tabs"
          :style="{ width: notices.length === 0 ? '200px' : '330px' }"
        >
          <el-empty
            v-if="notices.length === 0"
            description="暂无消息"
            :image-size="60"
          />
          <span v-else>
            <template v-for="item in notices" :key="item.key">
              <el-tab-pane :label="getLabel(item)" :name="`${item.key}`">
                <el-scrollbar max-height="330px">
                  <div class="noticeList-container">
                    <NoticeList :list="item.list" :emptyText="item.emptyText" />
                  </div>
                </el-scrollbar>
              </el-tab-pane>
            </template>
          </span>
        </el-tabs>
      </el-dropdown-menu>
    </template>
  </el-dropdown>
</template>

<style lang="scss" scoped>
.dropdown-badge {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 48px;
  cursor: pointer;

  .header-notice-icon {
    font-size: 18px;
  }
}

.dropdown-tabs {
  .noticeList-container {
    padding: 15px 24px 0;
  }

  :deep(.el-tabs__header) {
    margin: 0;
  }

  :deep(.el-tabs__nav-wrap)::after {
    height: 1px;
  }

  :deep(.el-tabs__nav-wrap) {
    padding: 0 36px;
  }
}
</style>
