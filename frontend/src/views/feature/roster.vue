<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  createDutyRoster,
  deleteDutyRoster,
  listDutyRoster,
  updateDutyRoster,
  type RosterEntry,
  type RosterPerson
} from "@/api/modules/roster";
import { backendErrorHint } from "@/api/http";

defineOptions({
  name: "FeatureRoster"
});

const MACHINE_SLOTS = 7;

type RosterRow = {
  key: string;
  dayId: number | null;
  nightId: number | null;
  dayName: string;
  nightName: string;
  slots: string[];
};

const loading = ref(false);
const saving = ref(false);
const backendHint = ref("");
const rows = ref<RosterRow[]>([]);
const machines = ref<string[]>([]);
const persons = ref<RosterPerson[]>([]);
const persistTimers = new Map<string, ReturnType<typeof setTimeout>>();

function errMessage(error: unknown, fallback: string) {
  const msg = (error as { response?: { data?: { message?: string } } })
    ?.response?.data?.message;
  return msg || fallback;
}

function emptySlots() {
  return Array.from({ length: MACHINE_SLOTS }, () => "");
}

function newKey() {
  return `row-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function padMachines(list: string[]) {
  const next = list
    .map(item => String(item || "").trim())
    .filter(Boolean)
    .slice(0, MACHINE_SLOTS);
  while (next.length < MACHINE_SLOTS) next.push("");
  return next;
}

function slotMachines(slots: string[]) {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const raw of slots) {
    const code = String(raw || "").trim();
    if (!code || seen.has(code)) continue;
    seen.add(code);
    result.push(code);
  }
  return result;
}

function machineKey(list: string[]) {
  return slotMachines(list).join("|");
}

function emptyRow(): RosterRow {
  return {
    key: newKey(),
    dayId: null,
    nightId: null,
    dayName: "",
    nightName: "",
    slots: emptySlots()
  };
}

function pairEntries(entries: RosterEntry[]): RosterRow[] {
  const days = entries.filter(row => row.duty === "白班");
  const nights = entries.filter(row => row.duty === "夜班");
  const usedNight = new Set<number>();
  const result: RosterRow[] = [];

  for (const day of days) {
    const key = machineKey(day.machines);
    const match =
      nights.find(
        night =>
          !usedNight.has(night.id) && machineKey(night.machines) === key
      ) || null;
    if (match) usedNight.add(match.id);
    result.push({
      key: `d-${day.id}`,
      dayId: day.id,
      nightId: match?.id ?? null,
      dayName: day.name,
      nightName: match?.name ?? "",
      slots: padMachines(day.machines)
    });
  }

  for (const night of nights) {
    if (usedNight.has(night.id)) continue;
    result.push({
      key: `n-${night.id}`,
      dayId: null,
      nightId: night.id,
      dayName: "",
      nightName: night.name,
      slots: padMachines(night.machines)
    });
  }

  return result;
}

function resolvePerson(name: string) {
  const text = name.trim();
  const found = persons.value.find(item => item.name === text);
  return {
    name: found?.name || text,
    person_id: found?.id ?? null
  };
}

const personNames = computed(() => persons.value.map(item => item.name));
const dayCount = computed(() => rows.value.filter(row => row.dayName.trim()).length);
const nightCount = computed(() =>
  rows.value.filter(row => row.nightName.trim()).length
);

function suggest(query: string, source: string[], limit = 0) {
  const q = query.trim().toLowerCase();
  const matched = q
    ? source.filter(item => item.toLowerCase().includes(q))
    : source;
  const list = limit > 0 ? matched.slice(0, limit) : matched;
  return list.map(value => ({ value }));
}

function suggestPersons(query: string, cb: (list: { value: string }[]) => void) {
  cb(suggest(query, personNames.value, 30));
}

/** 已占用机台（可排除当前正在编辑的格子，便于保留原值） */
function takenMachines(exceptRowKey?: string, exceptSlot?: number) {
  const taken = new Set<string>();
  for (const row of rows.value) {
    row.slots.forEach((raw, i) => {
      if (exceptRowKey && row.key === exceptRowKey && i === exceptSlot) return;
      const code = String(raw || "").trim();
      if (code) taken.add(code);
    });
  }
  return taken;
}

function suggestMachines(
  row: RosterRow,
  slotIndex: number,
  query: string,
  cb: (list: { value: string }[]) => void
) {
  const taken = takenMachines(row.key, slotIndex);
  const available = machines.value.filter(code => !taken.has(code));
  // 机台目录全量（未占用），不再截断前 20
  cb(suggest(query, available));
}

function isComplete(row: RosterRow) {
  return (
    Boolean(row.dayName.trim() || row.nightName.trim()) &&
    slotMachines(row.slots).length > 0
  );
}

function isBlank(row: RosterRow) {
  return (
    !row.dayName.trim() &&
    !row.nightName.trim() &&
    !slotMachines(row.slots).length &&
    row.dayId == null &&
    row.nightId == null
  );
}

async function load() {
  loading.value = true;
  backendHint.value = "";
  try {
    const res = await listDutyRoster();
    const data = res?.data;
    machines.value = data?.machines ?? [];
    persons.value = data?.persons ?? [];
    const next = pairEntries(data?.entries ?? []);
    rows.value = next.length ? next : [emptyRow()];
  } catch (error) {
    rows.value = [emptyRow()];
    backendHint.value = backendErrorHint(error);
  } finally {
    loading.value = false;
  }
}

async function persistRow(row: RosterRow) {
  if (isBlank(row)) return;
  if (!isComplete(row)) return;

  const selected = slotMachines(row.slots);
  saving.value = true;
  try {
    if (row.dayName.trim()) {
      const person = resolvePerson(row.dayName);
      const payload = {
        name: person.name,
        person_id: person.person_id,
        duty: "白班" as const,
        machines: selected
      };
      if (row.dayId != null) {
        await updateDutyRoster(row.dayId, payload);
      } else {
        const created = (await createDutyRoster(payload)) as {
          data?: { id?: number };
        };
        row.dayId = created?.data?.id ?? row.dayId;
      }
    } else if (row.dayId != null) {
      await deleteDutyRoster(row.dayId);
      row.dayId = null;
    }

    if (row.nightName.trim()) {
      const person = resolvePerson(row.nightName);
      const payload = {
        name: person.name,
        person_id: person.person_id,
        duty: "夜班" as const,
        machines: selected
      };
      if (row.nightId != null) {
        await updateDutyRoster(row.nightId, payload);
      } else {
        const created = (await createDutyRoster(payload)) as {
          data?: { id?: number };
        };
        row.nightId = created?.data?.id ?? row.nightId;
      }
    } else if (row.nightId != null) {
      await deleteDutyRoster(row.nightId);
      row.nightId = null;
    }
  } catch (error) {
    ElMessage.error(errMessage(error, "保存失败"));
  } finally {
    saving.value = false;
  }
}

function schedulePersist(row: RosterRow) {
  const prev = persistTimers.get(row.key);
  if (prev) clearTimeout(prev);
  persistTimers.set(
    row.key,
    setTimeout(() => {
      persistTimers.delete(row.key);
      void persistRow(row);
    }, 400)
  );
}

function addRow() {
  rows.value.push(emptyRow());
}

function flushPersists() {
  for (const timer of persistTimers.values()) clearTimeout(timer);
  persistTimers.clear();
}

const canSwap = computed(() =>
  rows.value.some(row => row.dayName.trim() || row.nightName.trim())
);

async function swapShifts() {
  if (!canSwap.value) {
    ElMessage.warning("没有可对调的人员");
    return;
  }
  try {
    await ElMessageBox.confirm(
      "将各行白班与夜班人员对调？机台不变。",
      "转班",
      { type: "warning", confirmButtonText: "对调", cancelButtonText: "取消" }
    );
  } catch {
    return;
  }

  flushPersists();
  const targets = rows.value.filter(
    row => row.dayName.trim() || row.nightName.trim()
  );
  for (const row of targets) {
    const dayName = row.dayName;
    const nightName = row.nightName;
    const dayId = row.dayId;
    const nightId = row.nightId;
    row.dayName = nightName;
    row.nightName = dayName;
    row.dayId = nightId;
    row.nightId = dayId;
  }

  saving.value = true;
  try {
    for (const row of targets) {
      await persistRow(row);
    }
    ElMessage.success("已对调白夜班");
  } finally {
    saving.value = false;
  }
}

async function onDelete(row: RosterRow, index: number) {
  if (isBlank(row) && rows.value.length > 1) {
    rows.value.splice(index, 1);
    return;
  }
  try {
    await ElMessageBox.confirm("删除这一行排班？", "确认", { type: "warning" });
  } catch {
    return;
  }
  try {
    if (row.dayId != null) await deleteDutyRoster(row.dayId);
    if (row.nightId != null) await deleteDutyRoster(row.nightId);
    rows.value.splice(index, 1);
    if (!rows.value.length) rows.value.push(emptyRow());
  } catch (error) {
    ElMessage.error(errMessage(error, "删除失败"));
  }
}

onMounted(load);
</script>

<template>
  <div class="p-4">
    <el-alert
      v-if="backendHint"
      class="mb-4"
      type="warning"
      :closable="false"
      :title="backendHint"
    />

    <div class="roster-card" v-loading="loading">
      <div class="roster-head">
        <div class="roster-head__title">
          <span>排班表</span>
          <span class="roster-stat roster-stat--day">白班 {{ dayCount }}</span>
          <span class="roster-stat roster-stat--night">夜班 {{ nightCount }}</span>
          <span v-if="saving" class="roster-save">保存中</span>
        </div>
        <div class="roster-head__actions">
          <el-button :disabled="!canSwap" @click="swapShifts">转班</el-button>
          <el-button type="primary" @click="addRow">添加一行</el-button>
        </div>
      </div>

      <div class="roster-sheet">
        <el-table
          :data="rows"
          border
          class="roster-table"
          empty-text="点「添加一行」，在格子里直接填写姓名和机台"
        >
          <el-table-column
            type="index"
            width="52"
            label="#"
            align="center"
            class-name="is-index"
            label-class-name="is-index"
          />
          <el-table-column label="班次" align="center">
            <el-table-column
              min-width="148"
              align="center"
              class-name="is-day"
              label-class-name="is-day"
            >
              <template #header>
                <div class="col-head" aria-label="白班 7:30–19:30">
                  <span class="col-head__title">白班</span>
                  <span class="col-head__note">7:30–19:30</span>
                </div>
              </template>
              <template #default="{ row }">
                <el-autocomplete
                  v-model="row.dayName"
                  class="cell-input"
                  :fetch-suggestions="suggestPersons"
                  placeholder="姓名"
                  value-key="value"
                  @input="schedulePersist(row)"
                  @blur="persistRow(row)"
                  @select="persistRow(row)"
                />
              </template>
            </el-table-column>
            <el-table-column
              min-width="148"
              align="center"
              class-name="is-night"
              label-class-name="is-night"
            >
              <template #header>
                <div class="col-head" aria-label="夜班 19:30–次日 7:30">
                  <span class="col-head__title">夜班</span>
                  <span class="col-head__note">19:30–次日 7:30</span>
                </div>
              </template>
              <template #default="{ row }">
                <el-autocomplete
                  v-model="row.nightName"
                  class="cell-input"
                  :fetch-suggestions="suggestPersons"
                  placeholder="姓名"
                  value-key="value"
                  @input="schedulePersist(row)"
                  @blur="persistRow(row)"
                  @select="persistRow(row)"
                />
              </template>
            </el-table-column>
          </el-table-column>
          <el-table-column label="负责机台" align="center">
            <el-table-column
              v-for="index in MACHINE_SLOTS"
              :key="`m-${index}`"
              :label="`机台${index}`"
              min-width="96"
              align="center"
              class-name="is-machine"
              label-class-name="is-machine"
            >
              <template #default="{ row }">
                <el-autocomplete
                  v-model="row.slots[index - 1]"
                  class="cell-input cell-input--machine"
                  :fetch-suggestions="
                    (q, cb) => suggestMachines(row, index - 1, q, cb)
                  "
                  placeholder="—"
                  value-key="value"
                  @input="schedulePersist(row)"
                  @blur="persistRow(row)"
                  @select="persistRow(row)"
                />
              </template>
            </el-table-column>
          </el-table-column>
          <el-table-column
            width="64"
            align="center"
            class-name="is-action"
            label-class-name="is-action"
          >
            <template #default="{ row, $index }">
              <el-button
                type="danger"
                link
                aria-label="删除这一行"
                @click="onDelete(row, $index)"
              >
                删除
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* 白班＝暖沙色，夜班＝品牌藏青系；固定色，兼容 NAS 旧浏览器 */
.roster-card {
  --roster-day-ink: #6f5630;
  --roster-day-mute: #8a7048;
  --roster-day-cell: #faf5ec;
  --roster-day-head: #e8dcc6;
  --roster-day-hover: #f2e9d8;
  --roster-day-pill: #ebe0cc;
  --roster-night-ink: #1e4e79;
  --roster-night-mute: #4d6f8f;
  --roster-night-cell: #eef3f7;
  --roster-night-head: #d4e0eb;
  --roster-night-hover: #e3ebf2;
  --roster-night-pill: #d5e2ec;
  --roster-line: #d5dae1;
  --roster-neutral: #f5f6f8;
  --roster-head-h: 44px;
  overflow: hidden;
  border: 1px solid var(--roster-line);
  border-radius: var(--la-radius-md);
  background: var(--el-bg-color);
}

.roster-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--la-space-md);
  box-sizing: border-box;
  width: 100%;
  height: var(--roster-head-h);
  margin: 0;
  padding: 0 var(--la-space-xl);
  border-bottom: 1px solid var(--roster-line);
  background: var(--roster-neutral);
}

.roster-head__actions {
  display: flex;
  flex-wrap: nowrap;
  align-items: center;
  gap: var(--la-space-sm);
  height: 100%;
}

.roster-head__actions :deep(.el-button) {
  height: 28px;
  margin: 0;
  padding: 0 12px;
}

.roster-head__title {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--la-space-sm);
  height: 100%;
  margin: 0;
  padding: 0;
  font-size: var(--la-page-title);
  font-weight: 650;
  line-height: 1;
  color: var(--el-text-color-primary);
}

.roster-stat {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 22px;
  padding: 0 8px;
  border-radius: var(--la-radius-sm);
  font-size: var(--la-text-2xs);
  font-weight: 600;
  line-height: 1;
  font-variant-numeric: tabular-nums;
}

.roster-stat--day {
  color: var(--roster-day-ink);
  background: var(--roster-day-pill);
}

.roster-stat--night {
  color: var(--roster-night-ink);
  background: var(--roster-night-pill);
}

.roster-save {
  font-size: var(--la-text-2xs);
  font-weight: 500;
  color: var(--el-color-primary);
}

/* 「白班 + 时段」整块；清零 EP 内边距/行高后再绝对居中 */
.col-head {
  position: absolute;
  top: 50%;
  left: 50%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  margin: 0;
  padding: 0;
  line-height: 1.25;
  text-align: center;
  white-space: nowrap;
  transform: translate(-50%, -50%);
}

.col-head__title {
  font-size: var(--la-text-xs);
  font-weight: 650;
  line-height: 1.25;
}

.col-head__note {
  font-size: 11px;
  font-weight: 500;
  line-height: 1.25;
  opacity: 0.85;
}

.roster-sheet {
  overflow: hidden;
}

.roster-table {
  --el-table-header-bg-color: var(--roster-neutral);
  --el-table-border-color: var(--roster-line);
  --el-table-header-padding: 0;
  --roster-subhead-h: 56px;
}

.roster-table :deep(.el-table__inner-wrapper::before) {
  display: none;
}

.roster-table :deep(th.el-table__cell) {
  padding: 0 !important;
  vertical-align: middle;
  font-size: var(--la-text-xs);
  font-weight: 650;
  letter-spacing: 0.01em;
  color: var(--el-text-color-primary);
  text-align: center;
}

.roster-table :deep(th.el-table__cell > .cell) {
  padding: 0 !important;
  line-height: normal !important;
}

.roster-table :deep(.el-table__header tr:first-child th.el-table__cell) {
  height: 36px;
}

.roster-table :deep(.el-table__header tr:first-child th.el-table__cell > .cell) {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 36px;
  line-height: 36px !important;
}

/* 白班/夜班：固定行高 + 零内边距，整块绝对居中 */
.roster-table :deep(th.el-table__cell.is-day),
.roster-table :deep(th.el-table__cell.is-night) {
  height: var(--roster-subhead-h) !important;
}

.roster-table :deep(th.el-table__cell.is-day > .cell),
.roster-table :deep(th.el-table__cell.is-night > .cell) {
  position: relative !important;
  box-sizing: border-box;
  height: var(--roster-subhead-h) !important;
  padding: 0 !important;
  margin: 0 !important;
  overflow: visible !important;
  line-height: 0 !important;
  font-size: 0;
  white-space: normal !important;
}

.roster-table :deep(th.el-table__cell.is-machine) {
  height: var(--roster-subhead-h) !important;
}

.roster-table :deep(th.el-table__cell.is-machine > .cell) {
  display: flex !important;
  align-items: center;
  justify-content: center;
  height: var(--roster-subhead-h) !important;
  padding: 0 !important;
  line-height: normal !important;
}

.roster-table :deep(.el-table--border),
.roster-table :deep(.el-table__inner-wrapper) {
  border-color: var(--roster-line);
}

.roster-table :deep(.el-table--border::after),
.roster-table :deep(.el-table--border::before),
.roster-table :deep(.el-table__inner-wrapper::after) {
  background-color: var(--roster-line);
}

.roster-table :deep(.el-table__cell) {
  border-right: 1px solid var(--roster-line) !important;
  border-bottom: 1px solid var(--roster-line) !important;
}

.roster-table :deep(.el-table__header-wrapper),
.roster-table :deep(.el-table__footer-wrapper) {
  border-bottom: 0;
}

.roster-table :deep(td.el-table__cell) {
  padding: 0;
  height: 44px;
}

.roster-table :deep(.el-table__cell.is-index) {
  color: var(--el-text-color-placeholder);
  font-variant-numeric: tabular-nums;
  font-size: var(--la-text-2xs);
  background: #fafbfc !important;
}

.roster-table :deep(th.el-table__cell.is-day) {
  color: var(--roster-day-ink);
  background: var(--roster-day-head) !important;
}

.roster-table :deep(th.el-table__cell.is-night) {
  color: var(--roster-night-ink);
  background: var(--roster-night-head) !important;
}

.roster-table :deep(th.el-table__cell.is-day .col-head__note) {
  color: var(--roster-day-mute);
}

.roster-table :deep(th.el-table__cell.is-night .col-head__note) {
  color: var(--roster-night-mute);
}

.roster-table :deep(th.el-table__cell.is-machine) {
  color: #4a5563;
  background: #eef0f3 !important;
}

.roster-table :deep(.el-table__cell.is-day) {
  background: var(--roster-day-cell) !important;
}

.roster-table :deep(.el-table__cell.is-night) {
  background: var(--roster-night-cell) !important;
}

.roster-table :deep(.el-table__cell.is-machine) {
  font-variant-numeric: tabular-nums;
  background: #fcfcfd !important;
}

.roster-table :deep(.el-table__body tr:hover > td.el-table__cell) {
  background: #f0f2f5;
}

.roster-table :deep(.el-table__body tr:hover > td.el-table__cell.is-day) {
  background: var(--roster-day-hover) !important;
}

.roster-table :deep(.el-table__body tr:hover > td.el-table__cell.is-night) {
  background: var(--roster-night-hover) !important;
}

.roster-table :deep(.el-table__body tr:hover > td.el-table__cell.is-machine) {
  background: #f4f6f8 !important;
}

.cell-input {
  width: 100%;
}

.roster-table :deep(.el-input__wrapper) {
  height: 44px;
  padding: 0 10px;
  box-shadow: none;
  background: transparent;
  border-radius: 0;
}

.roster-table :deep(.el-input__inner) {
  height: 44px;
  text-align: center;
}

.cell-input--machine :deep(.el-input__inner) {
  text-align: center;
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.02em;
}

.roster-table :deep(.el-input__wrapper.is-focus) {
  box-shadow: inset 0 0 0 1px var(--el-color-primary);
  background: #fff;
}

.roster-table :deep(.el-input__inner::placeholder) {
  color: #b0b7c3;
}

/* 聚焦时隐藏占位「—」横条，避免和光标叠在一起 */
.roster-table :deep(.el-input__wrapper.is-focus .el-input__inner::placeholder) {
  color: transparent;
  opacity: 0;
}

html.dark .roster-card {
  --roster-day-ink: #e6d3a8;
  --roster-day-mute: #c4b08a;
  --roster-day-cell: #2a261c;
  --roster-day-head: #3a3424;
  --roster-day-hover: #342e20;
  --roster-day-pill: #3a3424;
  --roster-night-ink: #a8c8e0;
  --roster-night-mute: #7fa3c0;
  --roster-night-cell: #1a2430;
  --roster-night-head: #243648;
  --roster-night-hover: #203040;
  --roster-night-pill: #243648;
  --roster-line: #2b313d;
  --roster-neutral: #1e222b;
}

html.dark .roster-table :deep(.el-table__cell.is-index),
html.dark .roster-table :deep(.el-table__cell.is-machine) {
  background: #171a21 !important;
}

html.dark .roster-table :deep(th.el-table__cell.is-machine) {
  background: #232833 !important;
  color: #c0c6d0;
}

html.dark .roster-table :deep(.el-input__wrapper.is-focus) {
  background: #171a21;
}
</style>
