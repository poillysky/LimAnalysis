<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  createProject,
  deleteProject,
  listProjects,
  updateProject,
  type MachineGroup,
  type ProjectItem,
  type ProjectOwners,
  type OwnerRoles
} from "@/api/modules/feature";
import { listPersons, type PersonItem } from "@/api/modules/persons";
import { backendErrorHint } from "@/api/http";
import { switchValue } from "@/utils/switchValue";

defineOptions({
  name: "FeatureIndex"
});

const DEFAULT_MACHINE_GROUPS: MachineGroup[] = [
  { name: "D", machines: Array.from({ length: 13 }, (_, i) => `D${i + 1}`) },
  { name: "N", machines: Array.from({ length: 14 }, (_, i) => `N${i + 1}`) },
  { name: "M", machines: Array.from({ length: 12 }, (_, i) => `M${i + 1}`) },
  { name: "K", machines: Array.from({ length: 6 }, (_, i) => `K${i + 1}`) },
  { name: "H", machines: Array.from({ length: 6 }, (_, i) => `H${i + 1}`) },
  { name: "I", machines: Array.from({ length: 6 }, (_, i) => `I${i + 1}`) }
];

const OWNER_AREAS = [
  { key: "injection", label: "注塑" },
  { key: "lim", label: "LIM" },
  { key: "finished", label: "成品" }
] as const;

const OWNER_ROLES = [
  { key: "production", label: "生产" },
  { key: "quality", label: "质量" },
  { key: "process", label: "工艺" }
] as const;

function emptyRoles(): OwnerRoles {
  return { production: [], quality: [], process: [] };
}

function emptyOwners(): ProjectOwners {
  return {
    injection: emptyRoles(),
    lim: emptyRoles(),
    finished: emptyRoles(),
    structure_rd: [],
    pm: []
  };
}

function cloneOwners(raw?: ProjectOwners | null): ProjectOwners {
  const base = emptyOwners();
  if (!raw) return base;
  for (const area of OWNER_AREAS) {
    const src = raw[area.key];
    if (!src) continue;
    base[area.key] = {
      production: [...(src.production || [])],
      quality: [...(src.quality || [])],
      process: [...(src.process || [])]
    };
  }
  base.structure_rd = [...(raw.structure_rd || [])];
  base.pm = [...(raw.pm || [])];
  return base;
}

function collectOwnerIds(owners?: ProjectOwners | null) {
  if (!owners) return [];
  const ids = new Set<number>();
  for (const area of OWNER_AREAS) {
    const src = owners[area.key];
    if (!src) continue;
    [...src.production, ...src.quality, ...src.process].forEach(id => ids.add(id));
  }
  owners.structure_rd?.forEach(id => ids.add(id));
  owners.pm?.forEach(id => ids.add(id));
  return [...ids];
}

const loading = ref(false);
const rows = ref<ProjectItem[]>([]);
const persons = ref<PersonItem[]>([]);
const machineGroups = ref<MachineGroup[]>(DEFAULT_MACHINE_GROUPS);
const backendHint = ref("");
const dialogVisible = ref(false);
const editingId = ref<string | null>(null);
const viewVisible = ref(false);
const viewRow = ref<ProjectItem | null>(null);
const form = reactive({
  display_name: "",
  enabled: true,
  machines: [] as string[],
  owners: emptyOwners()
});

function ownerSummary(row: ProjectItem) {
  const count = collectOwnerIds(row.owners).length;
  return count ? `${count} 人` : "未配置";
}

function personName(id: number) {
  return persons.value.find(item => item.id === id)?.name || `#${id}`;
}

function ownerDetail(row: ProjectItem) {
  const owners = row.owners;
  if (!owners) return [];
  const lines: { label: string; names: string[] }[] = [];
  for (const area of OWNER_AREAS) {
    const src = owners[area.key];
    if (!src) continue;
    for (const role of OWNER_ROLES) {
      const ids = src[role.key] || [];
      if (!ids.length) continue;
      lines.push({
        label: `${area.label} / ${role.label}`,
        names: ids.map(personName)
      });
    }
  }
  if (owners.structure_rd?.length) {
    lines.push({
      label: "结构研发",
      names: owners.structure_rd.map(personName)
    });
  }
  if (owners.pm?.length) {
    lines.push({ label: "PM", names: owners.pm.map(personName) });
  }
  return lines;
}

function machineNumber(code: string) {
  return code.replace(/^[A-Za-z]+/, "");
}

function isMachineOn(code: string) {
  return form.machines.includes(code);
}

function toggleMachine(code: string) {
  const next = new Set(form.machines);
  if (next.has(code)) next.delete(code);
  else next.add(code);
  form.machines = [...next];
}

function groupSelectedCount(group: MachineGroup) {
  return group.machines.filter(item => form.machines.includes(item)).length;
}

function isGroupChecked(group: MachineGroup) {
  return (
    group.machines.length > 0 &&
    group.machines.every(item => form.machines.includes(item))
  );
}

function isGroupPartial(group: MachineGroup) {
  const count = groupSelectedCount(group);
  return count > 0 && count < group.machines.length;
}

function toggleGroup(group: MachineGroup) {
  const next = new Set(form.machines);
  if (isGroupChecked(group)) {
    group.machines.forEach(item => next.delete(item));
  } else {
    group.machines.forEach(item => next.add(item));
  }
  form.machines = [...next];
}

const dialogTitle = computed(() =>
  editingId.value ? "编辑项目" : "新增项目"
);

const viewTitle = computed(() =>
  viewRow.value ? `${viewRow.value.display_name} · 负责人` : ""
);

function openView(row: ProjectItem) {
  if (!collectOwnerIds(row.owners).length) return;
  viewRow.value = row;
  viewVisible.value = true;
}

async function load() {
  loading.value = true;
  backendHint.value = "";
  try {
    const projectRes = await listProjects();
    rows.value = (projectRes?.data?.projects ?? []).map(item => {
      const name = item.display_name || item.project_id || "";
      const code = (item.sfc_code || "").trim();
      const sfc_code =
        code ||
        (name.toUpperCase().startsWith("SFC") ? name : name ? `SFC${name}` : "");
      return { ...item, sfc_code, btype: item.btype || "0" };
    });
    const groups = projectRes?.data?.machine_catalog?.groups;
    machineGroups.value = groups?.length ? groups : DEFAULT_MACHINE_GROUPS;
  } catch (error) {
    rows.value = [];
    backendHint.value = backendErrorHint(error);
  }
  try {
    const personRes = await listPersons();
    persons.value = personRes?.data?.persons ?? [];
  } catch {
    persons.value = [];
  } finally {
    loading.value = false;
  }
}

function resetForm() {
  form.display_name = "";
  form.enabled = true;
  form.machines = [];
  form.owners = emptyOwners();
}

function openCreate() {
  editingId.value = null;
  resetForm();
  dialogVisible.value = true;
}

function openEdit(row: ProjectItem) {
  editingId.value = row.project_id;
  form.display_name = row.display_name;
  form.enabled = row.enabled;
  form.machines = [...(row.machines || [])];
  form.owners = cloneOwners(row.owners);
  dialogVisible.value = true;
}

async function submit() {
  if (!form.display_name.trim()) {
    ElMessage.warning("请填写名称");
    return;
  }
  const payload = {
    display_name: form.display_name.trim(),
    enabled: form.enabled,
    machines: [...form.machines],
    owners: cloneOwners(form.owners)
  };
  try {
    if (editingId.value) {
      await updateProject(editingId.value, payload);
      ElMessage.success("已保存");
    } else {
      await createProject(payload);
      ElMessage.success("已添加");
    }
    dialogVisible.value = false;
    await load();
  } catch {
    ElMessage.error(editingId.value ? "保存失败" : "添加失败（后端未启动或名称无法生成编号）");
  }
}

async function onEnabledChange(row: ProjectItem, value: boolean) {
  try {
    await updateProject(row.project_id, { enabled: value });
  } catch {
    row.enabled = !value;
    ElMessage.error("更新失败");
  }
}

async function onDelete(row: ProjectItem) {
  try {
    await ElMessageBox.confirm(`删除项目 ${row.display_name}？`, "确认", {
      type: "warning"
    });
  } catch {
    return;
  }
  try {
    await deleteProject(row.project_id);
    ElMessage.success("已删除");
    await load();
  } catch {
    ElMessage.error("删除失败");
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
    <el-card shadow="never">
      <template #header>
        <div class="flex items-center justify-between">
          <span>项目管理</span>
          <el-button type="primary" @click="openCreate">新增项目</el-button>
        </div>
      </template>
      <el-table v-loading="loading" :data="rows" stripe>
        <el-table-column prop="display_name" label="名称" width="120" />
        <el-table-column prop="project_id" label="项目ID" width="140" />
        <el-table-column prop="prefix" label="前缀" width="130" />
        <el-table-column label="机台" min-width="280">
          <template #default="{ row }">
            <span v-if="(row.machines || []).length" class="machine-list">
              {{ (row.machines || []).join("  ") }}
            </span>
            <span v-else class="cell-muted">未配置</span>
          </template>
        </el-table-column>
        <el-table-column label="负责人" width="88">
          <template #default="{ row }">
            <button
              v-if="collectOwnerIds(row.owners).length"
              type="button"
              class="cell-link"
              @click="openView(row)"
            >
              {{ ownerSummary(row) }}
            </button>
            <span v-else class="cell-muted">未配置</span>
          </template>
        </el-table-column>
        <el-table-column label="启用" width="80">
          <template #default="{ row }">
            <el-switch
              v-model="row.enabled"
              @change="val => onEnabledChange(row, switchValue(val))"
            />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button type="primary" link @click="openEdit(row)">编辑</el-button>
            <el-button type="danger" link @click="onDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="dialogVisible" :title="dialogTitle" width="640px">
      <el-form label-width="72px">
        <el-form-item label="名称" required>
          <el-input v-model="form.display_name" placeholder="例如 Eelspkr" />
        </el-form-item>
        <el-form-item label="机台">
          <div class="machine-board">
            <div
              v-for="group in machineGroups"
              :key="group.name"
              class="machine-row"
            >
              <button
                type="button"
                class="machine-line"
                :class="{
                  'is-on': isGroupChecked(group),
                  'is-partial': isGroupPartial(group)
                }"
                :title="`全选/取消 ${group.name} 线`"
                @click="toggleGroup(group)"
              >
                {{ group.name }}
              </button>
              <button
                v-for="item in group.machines"
                :key="item"
                type="button"
                class="machine-cell"
                :class="{ 'is-on': isMachineOn(item) }"
                :title="item"
                @click="toggleMachine(item)"
              >
                {{ machineNumber(item) }}
              </button>
            </div>
            <div class="machine-hint">
              已选 {{ form.machines.length }} 台 · 点线号全选
            </div>
          </div>
        </el-form-item>
        <el-form-item label="负责人">
          <div class="owner-board">
            <div class="owner-matrix">
              <span />
              <span
                v-for="role in OWNER_ROLES"
                :key="role.key"
                class="owner-head"
              >
                {{ role.label }}
              </span>
              <template v-for="area in OWNER_AREAS" :key="area.key">
                <span class="owner-area">{{ area.label }}</span>
                <el-select
                  v-for="role in OWNER_ROLES"
                  :key="`${area.key}-${role.key}`"
                  v-model="form.owners[area.key][role.key]"
                  multiple
                  filterable
                  collapse-tags
                  collapse-tags-tooltip
                  clearable
                  size="small"
                  placeholder="人员"
                >
                  <el-option
                    v-for="person in persons"
                    :key="person.id"
                    :label="person.name"
                    :value="person.id"
                  />
                </el-select>
              </template>
            </div>
            <div class="owner-solo">
              <span class="owner-area">结构研发</span>
              <el-select
                v-model="form.owners.structure_rd"
                multiple
                filterable
                collapse-tags
                collapse-tags-tooltip
                clearable
                size="small"
                placeholder="选择人员"
              >
                <el-option
                  v-for="person in persons"
                  :key="person.id"
                  :label="person.name"
                  :value="person.id"
                />
              </el-select>
              <span class="owner-area">PM</span>
              <el-select
                v-model="form.owners.pm"
                multiple
                filterable
                collapse-tags
                collapse-tags-tooltip
                clearable
                size="small"
                placeholder="选择人员"
              >
                <el-option
                  v-for="person in persons"
                  :key="person.id"
                  :label="person.name"
                  :value="person.id"
                />
              </el-select>
            </div>
          </div>
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="form.enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submit">确定</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="viewVisible" :title="viewTitle" width="480px">
      <div v-if="viewRow" class="detail-pop">
        <div
          v-for="line in ownerDetail(viewRow)"
          :key="line.label"
          class="detail-row"
        >
          <span class="detail-k">{{ line.label }}</span>
          <span>{{ line.names.join("、") }}</span>
        </div>
      </div>
      <template #footer>
        <el-button type="primary" @click="viewVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.machine-board {
  display: flex;
  flex-direction: column;
  gap: 5px;
  width: 100%;
}

.machine-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 3px;
}

.machine-line,
.machine-cell {
  margin: 0;
  padding: 0;
  border: 1px solid var(--el-border-color);
  background: var(--el-fill-color-blank);
  color: var(--el-text-color-regular);
  cursor: pointer;
  line-height: 1;
  transition:
    background-color 0.12s ease,
    border-color 0.12s ease,
    color 0.12s ease,
    transform 0.08s ease;
}

.machine-line {
  width: 28px;
  height: 24px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 650;
}

.machine-cell {
  width: 24px;
  height: 24px;
  border-radius: 4px;
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}

.machine-line:hover,
.machine-cell:hover {
  border-color: var(--el-color-primary-light-5);
}

.machine-line:active,
.machine-cell:active {
  transform: scale(0.96);
}

.machine-line.is-on,
.machine-cell.is-on {
  background: var(--el-color-primary);
  border-color: var(--el-color-primary);
  color: #fff;
}

.machine-line.is-partial {
  background: var(--el-color-primary-light-8);
  border-color: var(--el-color-primary);
  color: var(--el-color-primary);
}

.machine-hint {
  margin-top: 2px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.owner-board {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 100%;
}

.owner-matrix {
  display: grid;
  grid-template-columns: 52px minmax(0, 1fr) minmax(0, 1fr) minmax(0, 1fr);
  gap: 6px 8px;
  align-items: center;
}

.owner-solo {
  display: grid;
  grid-template-columns: 52px minmax(0, 1fr);
  gap: 6px 8px;
  align-items: center;
}

.owner-head {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  text-align: center;
}

.owner-area {
  color: var(--el-text-color-regular);
  font-size: 12px;
  font-weight: 600;
}

.cell-link {
  margin: 0;
  padding: 0;
  border: 0;
  background: none;
  color: var(--el-color-primary);
  cursor: pointer;
  font: inherit;
}

.cell-link:hover {
  text-decoration: underline;
}

.cell-muted {
  color: var(--el-text-color-secondary);
}

.machine-list {
  display: inline-block;
  line-height: 1.5;
  word-break: break-word;
}

.detail-pop {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.detail-row {
  display: grid;
  grid-template-columns: max-content 1fr;
  gap: 8px 16px;
  font-size: 14px;
  line-height: 1.5;
}

.detail-k {
  color: var(--el-text-color-secondary);
}
</style>
