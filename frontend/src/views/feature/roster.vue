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

const MACHINE_SLOTS = 6;

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

function suggest(query: string, source: string[]) {
  const q = query.trim().toLowerCase();
  const matched = q
    ? source.filter(item => item.toLowerCase().includes(q))
    : source;
  return matched.slice(0, 20).map(value => ({ value }));
}

function suggestPersons(query: string, cb: (list: { value: string }[]) => void) {
  cb(suggest(query, personNames.value));
}

function suggestMachines(query: string, cb: (list: { value: string }[]) => void) {
  cb(suggest(query, machines.value));
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

    <el-card shadow="never" class="roster-card">
      <template #header>
        <div class="roster-head">
          <div class="roster-head__title">
            <span>排班表</span>
            <span class="roster-stat roster-stat--day">白班 {{ dayCount }}</span>
            <span class="roster-stat roster-stat--night">夜班 {{ nightCount }}</span>
            <span class="roster-hours">白班 7:30–19:30 · 夜班 19:30–次日 7:30</span>
            <span v-if="saving" class="roster-save">保存中</span>
          </div>
          <div class="roster-head__actions">
            <el-button :disabled="!canSwap" @click="swapShifts">转班</el-button>
            <el-button type="primary" @click="addRow">添加一行</el-button>
          </div>
        </div>
      </template>

      <div class="roster-sheet">
        <el-table
          v-loading="loading"
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
                <div class="col-head">
                  <span>白班</span>
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
                <div class="col-head">
                  <span>夜班</span>
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
              :label="String(index)"
              min-width="108"
              align="center"
              class-name="is-machine"
              label-class-name="is-machine"
            >
              <template #default="{ row }">
                <el-autocomplete
                  v-model="row.slots[index - 1]"
                  class="cell-input cell-input--machine"
                  :fetch-suggestions="suggestMachines"
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
        <button type="button" class="roster-add" @click="addRow">
          添加一行
        </button>
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.roster-card :deep(.el-card__header) {
  padding: 14px 18px;
}

.roster-card :deep(.el-card__body) {
  padding: 0;
}

.roster-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.roster-head__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.roster-head__title {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  font-size: 15px;
  font-weight: 600;
}

.roster-stat {
  display: inline-flex;
  align-items: center;
  height: 24px;
  padding: 0 9px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 500;
  font-variant-numeric: tabular-nums;
}

.roster-stat--day {
  color: #8a5a12;
  background: color-mix(in srgb, #e6a23c 22%, var(--el-bg-color));
}

.roster-stat--night {
  color: #1d4f91;
  background: color-mix(in srgb, #409eff 20%, var(--el-bg-color));
}

.roster-hours {
  font-size: 12px;
  font-weight: 500;
  color: var(--el-text-color-secondary);
}

.roster-save {
  font-size: 12px;
  font-weight: 500;
  color: var(--el-color-primary);
}

.col-head {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  line-height: 1.2;
}

.col-head__note {
  font-size: 11px;
  font-weight: 500;
  color: var(--el-text-color-secondary);
}

.roster-sheet {
  overflow: hidden;
  --roster-line: #c8c8c8;
}

.roster-table {
  --el-table-header-bg-color: color-mix(
    in srgb,
    var(--el-fill-color-light) 80%,
    var(--el-bg-color)
  );
  --el-table-border-color: var(--roster-line);
}

.roster-table :deep(.el-table__inner-wrapper::before) {
  display: none;
}

.roster-table :deep(th.el-table__cell) {
  height: 48px;
  padding: 4px 0;
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.02em;
  color: var(--el-text-color-primary);
  text-align: center;
}

.roster-table :deep(th.el-table__cell .cell) {
  text-align: center;
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
  height: 46px;
}

.roster-table :deep(.el-table__cell.is-index) {
  color: var(--el-text-color-placeholder);
  font-variant-numeric: tabular-nums;
  font-size: 12px;
}

.roster-table :deep(.el-table__cell.is-day) {
  background: color-mix(in srgb, #e6a23c 10%, var(--el-bg-color));
}

.roster-table :deep(.el-table__cell.is-night) {
  background: color-mix(in srgb, #409eff 9%, var(--el-bg-color));
}

.roster-table :deep(.el-table__cell.is-machine) {
  font-variant-numeric: tabular-nums;
}

.roster-table :deep(.el-table__body tr:hover > td.el-table__cell) {
  background: color-mix(in srgb, var(--el-color-primary) 6%, var(--el-bg-color));
}

.roster-table :deep(.el-table__body tr:hover > td.el-table__cell.is-day) {
  background: color-mix(in srgb, #e6a23c 16%, var(--el-bg-color));
}

.roster-table :deep(.el-table__body tr:hover > td.el-table__cell.is-night) {
  background: color-mix(in srgb, #409eff 14%, var(--el-bg-color));
}

.cell-input {
  width: 100%;
}

.roster-table :deep(.el-input__wrapper) {
  height: 46px;
  padding: 0 10px;
  box-shadow: none;
  background: transparent;
  border-radius: 0;
}

.roster-table :deep(.el-input__inner) {
  height: 46px;
  text-align: center;
}

.cell-input--machine :deep(.el-input__inner) {
  text-align: center;
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.02em;
}

.roster-table :deep(.el-input__wrapper.is-focus) {
  box-shadow: inset 0 0 0 1px var(--el-color-primary);
  background: var(--el-bg-color);
}

.roster-table :deep(.el-input__inner::placeholder) {
  color: color-mix(in srgb, var(--el-text-color-placeholder) 70%, transparent);
}

.roster-add {
  display: flex;
  width: 100%;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 42px;
  border: 0;
  border-top: 1px solid var(--roster-line);
  background: color-mix(in srgb, var(--el-fill-color-lighter) 70%, var(--el-bg-color));
  color: var(--el-text-color-regular);
  font-size: 13px;
  cursor: pointer;
}

.roster-add:hover {
  color: var(--el-color-primary);
  background: color-mix(in srgb, var(--el-color-primary) 8%, var(--el-bg-color));
}

.roster-add:focus-visible {
  outline: 2px solid var(--el-color-primary);
  outline-offset: -2px;
}

html.dark .roster-stat--day {
  color: #f3d19e;
}

html.dark .roster-stat--night {
  color: #a0cfff;
}

html.dark .roster-sheet {
  --roster-line: #5c5c5c;
}
</style>
