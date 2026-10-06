<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  createUser,
  deleteUser,
  listUsers,
  updateUser,
  type UserItem
} from "@/api/modules/users";
import { backendErrorHint } from "@/api/http";
import { switchValue } from "@/utils/switchValue";

defineOptions({
  name: "FeatureUsers"
});

const loading = ref(false);
const rows = ref<UserItem[]>([]);
const backendHint = ref("");
const dialogVisible = ref(false);
const editing = ref<string | null>(null);
const form = reactive({
  username: "",
  nickname: "",
  password: "",
  role: "common" as UserItem["role"],
  enabled: true
});

function errMessage(error: unknown, fallback: string) {
  const msg = (error as { response?: { data?: { message?: string } } })
    ?.response?.data?.message;
  return msg || fallback;
}

async function load() {
  loading.value = true;
  backendHint.value = "";
  try {
    const res = await listUsers();
    rows.value = res?.data?.users ?? [];
  } catch (error) {
    rows.value = [];
    backendHint.value = backendErrorHint(error);
  } finally {
    loading.value = false;
  }
}

function openCreate() {
  editing.value = null;
  form.username = "";
  form.nickname = "";
  form.password = "";
  form.role = "common";
  form.enabled = true;
  dialogVisible.value = true;
}

function openEdit(row: UserItem) {
  editing.value = row.username;
  form.username = row.username;
  form.nickname = row.nickname;
  form.password = "";
  form.role = row.role;
  form.enabled = row.enabled;
  dialogVisible.value = true;
}

async function submit() {
  if (!editing.value && !form.username.trim()) {
    ElMessage.warning("请填写账号");
    return;
  }
  if (!editing.value && form.password.length < 6) {
    ElMessage.warning("密码至少 6 位");
    return;
  }
  if (editing.value && form.password && form.password.length < 6) {
    ElMessage.warning("密码至少 6 位");
    return;
  }
  try {
    if (editing.value) {
      const payload: Parameters<typeof updateUser>[1] = {
        nickname: form.nickname.trim() || form.username,
        role: form.role,
        enabled: form.enabled
      };
      if (form.password) payload.password = form.password;
      await updateUser(editing.value, payload);
      ElMessage.success("已保存");
    } else {
      await createUser({
        username: form.username.trim(),
        nickname: form.nickname.trim() || form.username.trim(),
        password: form.password,
        role: form.role,
        enabled: form.enabled
      });
      ElMessage.success("已添加");
    }
    dialogVisible.value = false;
    await load();
  } catch (error) {
    ElMessage.error(errMessage(error, "保存失败"));
  }
}

async function onEnabledChange(row: UserItem, value: boolean) {
  try {
    await updateUser(row.username, { enabled: value });
  } catch (error) {
    row.enabled = !value;
    ElMessage.error(errMessage(error, "更新失败"));
  }
}

async function onDelete(row: UserItem) {
  try {
    await ElMessageBox.confirm(`删除用户 ${row.username}？`, "确认", {
      type: "warning"
    });
  } catch {
    return;
  }
  try {
    await deleteUser(row.username);
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
        <div class="flex items-center justify-between">
          <span>用户管理</span>
          <el-button type="primary" @click="openCreate">新增用户</el-button>
        </div>
      </template>
      <el-table v-loading="loading" :data="rows" stripe>
        <el-table-column prop="username" label="账号" min-width="140" />
        <el-table-column prop="nickname" label="姓名" min-width="120" />
        <el-table-column label="角色" width="110">
          <template #default="{ row }">
            {{ row.role === "admin" ? "管理员" : "普通用户" }}
          </template>
        </el-table-column>
        <el-table-column label="启用" width="90">
          <template #default="{ row }">
            <el-switch
              v-model="row.enabled"
              @change="val => onEnabledChange(row, switchValue(val))"
            />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="140">
          <template #default="{ row }">
            <el-button type="primary" link @click="openEdit(row)">编辑</el-button>
            <el-button type="danger" link @click="onDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog
      v-model="dialogVisible"
      :title="editing ? '编辑用户' : '新增用户'"
      width="480px"
    >
      <el-form label-width="90px">
        <el-form-item label="账号" required>
          <el-input
            v-model="form.username"
            :disabled="Boolean(editing)"
            placeholder="字母、数字或下划线"
          />
        </el-form-item>
        <el-form-item label="姓名">
          <el-input v-model="form.nickname" />
        </el-form-item>
        <el-form-item :label="editing ? '新密码' : '密码'" :required="!editing">
          <el-input
            v-model="form.password"
            type="password"
            show-password
            :placeholder="editing ? '不改请留空' : '至少 6 位'"
          />
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="form.role" class="w-full">
            <el-option label="管理员" value="admin" />
            <el-option label="普通用户" value="common" />
          </el-select>
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
  </div>
</template>
