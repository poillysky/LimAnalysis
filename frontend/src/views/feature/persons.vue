<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  createPerson,
  deletePerson,
  listPersons,
  updatePerson,
  type PersonItem,
  type PersonOptions
} from "@/api/modules/persons";
import { backendErrorHint } from "@/api/http";

defineOptions({
  name: "FeaturePersons"
});

const DEFAULT_OPTIONS: PersonOptions = {
  shifts: ["长白班", "两班倒", "三班倒"],
  departments: [
    "注塑机调试",
    "注塑机影像",
    "自动化调试",
    "模具钳工",
    "外观线",
    "车间工艺",
    "管理"
  ]
};

const loading = ref(false);
const rows = ref<PersonItem[]>([]);
const options = ref<PersonOptions>({ ...DEFAULT_OPTIONS });
const keyword = ref("");
const backendHint = ref("");
const dialogVisible = ref(false);
const editing = ref<number | null>(null);
const form = reactive({
  name: "",
  phone: "",
  shift: "",
  department: ""
});

function errMessage(error: unknown, fallback: string) {
  const msg = (error as { response?: { data?: { message?: string } } })
    ?.response?.data?.message;
  return msg || fallback;
}

const filtered = computed(() => {
  const q = keyword.value.trim().toLowerCase();
  if (!q) return rows.value;
  return rows.value.filter(row => row.name.toLowerCase().includes(q));
});

function withCurrent(list: string[], current: string) {
  const value = current.trim();
  if (!value || list.includes(value)) return list;
  return [...list, value];
}

const shiftChoices = computed(() => withCurrent(options.value.shifts, form.shift));
const departmentChoices = computed(() =>
  withCurrent(options.value.departments, form.department)
);

async function load() {
  loading.value = true;
  backendHint.value = "";
  try {
    const res = await listPersons();
    rows.value = res?.data?.persons ?? [];
    const next = res?.data?.options;
    options.value = {
      shifts: next?.shifts?.length ? next.shifts : DEFAULT_OPTIONS.shifts,
      departments: next?.departments?.length
        ? next.departments
        : DEFAULT_OPTIONS.departments
    };
  } catch (error) {
    rows.value = [];
    backendHint.value = backendErrorHint(error);
  } finally {
    loading.value = false;
  }
}

function resetForm() {
  form.name = "";
  form.phone = "";
  form.shift = "";
  form.department = "";
}

function openCreate() {
  editing.value = null;
  resetForm();
  dialogVisible.value = true;
}

function openEdit(row: PersonItem) {
  editing.value = row.id;
  form.name = row.name;
  form.phone = row.phone;
  form.shift = row.shift;
  form.department = row.department;
  dialogVisible.value = true;
}

async function submit() {
  if (!form.name.trim()) {
    ElMessage.warning("请填写姓名");
    return;
  }
  const payload = {
    name: form.name.trim(),
    phone: form.phone.trim(),
    shift: form.shift.trim(),
    department: form.department.trim()
  };
  try {
    if (editing.value != null) {
      await updatePerson(editing.value, payload);
      ElMessage.success("已保存");
    } else {
      await createPerson(payload);
      ElMessage.success("已添加");
    }
    dialogVisible.value = false;
    await load();
  } catch (error) {
    ElMessage.error(errMessage(error, "保存失败"));
  }
}

async function onDelete(row: PersonItem) {
  try {
    await ElMessageBox.confirm(`删除 ${row.name}？`, "确认", {
      type: "warning"
    });
  } catch {
    return;
  }
  try {
    await deletePerson(row.id);
    ElMessage.success("已删除");
    await load();
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
    <el-card shadow="never">
      <template #header>
        <div class="flex flex-wrap items-center justify-between gap-3">
          <span>人员管理</span>
          <div class="flex items-center gap-2">
            <el-input
              v-model="keyword"
              clearable
              class="w-52"
              placeholder="搜索姓名"
            />
            <el-button type="primary" @click="openCreate">新增人员</el-button>
          </div>
        </div>
      </template>
      <el-table v-loading="loading" :data="filtered" stripe>
        <el-table-column prop="name" label="姓名" min-width="120" />
        <el-table-column prop="phone" label="联系电话" min-width="140" />
        <el-table-column prop="shift" label="班制" min-width="100" />
        <el-table-column prop="department" label="部门" min-width="140" />
        <el-table-column label="操作" width="140" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" link @click="openEdit(row)">编辑</el-button>
            <el-button type="danger" link @click="onDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog
      v-model="dialogVisible"
      :title="editing != null ? '编辑人员' : '新增人员'"
      width="480px"
    >
      <el-form label-width="90px">
        <el-form-item label="姓名" required>
          <el-input v-model="form.name" />
        </el-form-item>
        <el-form-item label="联系电话">
          <el-input v-model="form.phone" />
        </el-form-item>
        <el-form-item label="班制">
          <el-select
            v-model="form.shift"
            clearable
            class="w-full"
            placeholder="请选择班制"
          >
            <el-option
              v-for="item in shiftChoices"
              :key="item"
              :label="item"
              :value="item"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="部门">
          <el-select
            v-model="form.department"
            clearable
            class="w-full"
            placeholder="请选择部门"
          >
            <el-option
              v-for="item in departmentChoices"
              :key="item"
              :label="item"
              :value="item"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submit">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>
