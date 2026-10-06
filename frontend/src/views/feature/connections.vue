<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import {
  listConnections,
  saveConnections,
  testConnection,
  testDbweb,
  testMetabase,
  type ConnStatus,
  type PgConnForm
} from "@/api/modules/connections";
import { backendErrorHint } from "@/api/http";

defineOptions({
  name: "FeatureConnections"
});

type Target = "raw" | "dwh" | "defect";

const router = useRouter();

const CARDS: { key: Target; title: string }[] = [
  { key: "raw", title: "原始数据库" },
  { key: "dwh", title: "ETL数据库" },
  { key: "defect", title: "次品数据库" }
];

const loading = ref(false);
const saving = ref(false);
const testing = ref<Target | "dbweb" | "metabase" | "">("");
const backendHint = ref("");
const status = reactive<{
  raw: ConnStatus;
  dwh: ConnStatus;
  defect: ConnStatus;
  dbweb: ConnStatus;
  metabase: ConnStatus;
}>({
  raw: { ok: false, error: null },
  dwh: { ok: false, error: null },
  defect: { ok: false, error: null },
  dbweb: { ok: false, error: null },
  metabase: { ok: false, error: null }
});
const passwordSet = reactive({ raw: false, dwh: false, defect: false, metabase: false });
const form = reactive({
  raw: emptyConn(),
  dwh: emptyConn(),
  defect: emptyConn()
});
const dbweb = reactive({
  scheme: "http",
  host: "127.0.0.1",
  port: 18080,
  sqlite_path: "/data/meta/lim_meta.sqlite"
});
const metabase = reactive({
  scheme: "http",
  host: "127.0.0.1",
  port: 13000,
  username: "",
  password: ""
});

const dbwebUrl = computed(() => {
  const host = dbweb.host.trim() || "127.0.0.1";
  const port = Number(dbweb.port) || 18080;
  const scheme = dbweb.scheme === "https" ? "https" : "http";
  return `${scheme}://${host}:${port}`;
});

const dbwebEndpoint = computed(() => {
  const path = dbweb.sqlite_path.trim();
  return path ? `${dbwebUrl.value} · ${path}` : dbwebUrl.value;
});

const metabaseUrl = computed(() => {
  const host = metabase.host.trim() || "127.0.0.1";
  const port = Number(metabase.port) || 13000;
  const scheme = metabase.scheme === "https" ? "https" : "http";
  return `${scheme}://${host}:${port}`;
});

function emptyConn(): PgConnForm {
  return {
    host: "127.0.0.1",
    port: 5432,
    database: "",
    username: "",
    password: ""
  };
}

function applyPublic(
  target: Target,
  item: {
    host: string;
    port: number;
    database: string;
    username: string;
    password_set: boolean;
  }
) {
  form[target].host = item.host;
  form[target].port = item.port;
  form[target].database = item.database;
  form[target].username = item.username;
  form[target].password = "";
  passwordSet[target] = item.password_set;
}

function applyDbwebUrl(url: string) {
  try {
    const parsed = new URL(url);
    dbweb.scheme = parsed.protocol === "https:" ? "https" : "http";
    dbweb.host = parsed.hostname || "127.0.0.1";
    dbweb.port = Number(parsed.port) || (dbweb.scheme === "https" ? 443 : 18080);
  } catch {
    /* keep current */
  }
}

function applyMetabaseUrl(url: string) {
  try {
    const parsed = new URL(url);
    metabase.scheme = parsed.protocol === "https:" ? "https" : "http";
    metabase.host = parsed.hostname || "127.0.0.1";
    metabase.port =
      Number(parsed.port) || (metabase.scheme === "https" ? 443 : 13000);
  } catch {
    /* keep current */
  }
}

function applyMetabasePublic(
  item: { url?: string; username?: string; password_set?: boolean },
  opts?: { clearPassword?: boolean }
) {
  if (item.url) applyMetabaseUrl(item.url);
  if (typeof item.username === "string") metabase.username = item.username;
  passwordSet.metabase = Boolean(item.password_set);
  if (opts?.clearPassword) metabase.password = "";
}

function endpoint(target: Target) {
  const item = form[target];
  const host = item.host.trim() || "—";
  const db = item.database.trim();
  return db ? `${host}:${item.port} / ${db}` : `${host}:${item.port}`;
}

async function load() {
  loading.value = true;
  backendHint.value = "";
  try {
    const res = await listConnections();
    const data = res?.data;
    if (data?.connections?.raw) applyPublic("raw", data.connections.raw);
    if (data?.connections?.dwh) applyPublic("dwh", data.connections.dwh);
    if (data?.connections?.defect) applyPublic("defect", data.connections.defect);
    if (data?.dbweb?.url) applyDbwebUrl(data.dbweb.url);
    else if (import.meta.env.VITE_DBWEB_URL) {
      applyDbwebUrl(String(import.meta.env.VITE_DBWEB_URL));
    }
    if (data?.dbweb?.sqlite_path) dbweb.sqlite_path = data.dbweb.sqlite_path;
    if (data?.metabase) applyMetabasePublic(data.metabase, { clearPassword: true });
    if (data?.status?.raw) Object.assign(status.raw, data.status.raw);
    if (data?.status?.dwh) Object.assign(status.dwh, data.status.dwh);
    if (data?.status?.defect) Object.assign(status.defect, data.status.defect);
    if (data?.status?.dbweb) Object.assign(status.dbweb, data.status.dbweb);
    if (data?.status?.metabase) Object.assign(status.metabase, data.status.metabase);
  } catch (error) {
    backendHint.value = backendErrorHint(error);
  } finally {
    loading.value = false;
  }
}

function payload(target: Target): PgConnForm {
  return {
    host: form[target].host.trim(),
    port: Number(form[target].port) || 5432,
    database: form[target].database.trim(),
    username: form[target].username.trim(),
    password: form[target].password
  };
}

async function onTest(target: Target) {
  testing.value = target;
  try {
    const res = await testConnection({ target, ...payload(target) });
    const ok = Boolean(res?.data?.ok);
    status[target].ok = ok;
    status[target].error = res?.data?.error ?? null;
    if (ok) ElMessage.success("连接成功");
    else ElMessage.error(res?.data?.error || "连接失败");
  } catch (error) {
    ElMessage.error(backendErrorHint(error));
  } finally {
    testing.value = "";
  }
}

async function onTestDbweb() {
  testing.value = "dbweb";
  try {
    const res = await testDbweb({ url: dbwebUrl.value });
    const ok = Boolean(res?.data?.ok);
    status.dbweb.ok = ok;
    status.dbweb.error = res?.data?.error ?? null;
    if (ok) ElMessage.success("连接成功");
    else ElMessage.error(res?.data?.error || "连接失败");
  } catch (error) {
    ElMessage.error(backendErrorHint(error));
  } finally {
    testing.value = "";
  }
}

async function onTestMetabase() {
  testing.value = "metabase";
  try {
    const res = await testMetabase({
      url: metabaseUrl.value,
      username: metabase.username.trim(),
      password: metabase.password
    });
    const ok = Boolean(res?.data?.ok);
    status.metabase.ok = ok;
    status.metabase.error = res?.data?.error ?? null;
    if (ok) ElMessage.success("连接成功");
    else ElMessage.error(res?.data?.error || "连接失败");
  } catch (error) {
    ElMessage.error(backendErrorHint(error));
  } finally {
    testing.value = "";
  }
}

async function onSave() {
  saving.value = true;
  try {
    const res = await saveConnections({
      raw: payload("raw"),
      dwh: payload("dwh"),
      defect: payload("defect"),
      dbweb: {
        url: dbwebUrl.value,
        sqlite_path: dbweb.sqlite_path.trim() || "/data/meta/lim_meta.sqlite"
      },
      metabase: {
        url: metabaseUrl.value,
        username: metabase.username.trim(),
        password: metabase.password
      }
    });
    const data = res?.data;
    if (data?.connections?.raw) applyPublic("raw", data.connections.raw);
    if (data?.connections?.dwh) applyPublic("dwh", data.connections.dwh);
    if (data?.connections?.defect) applyPublic("defect", data.connections.defect);
    if (data?.dbweb?.sqlite_path) dbweb.sqlite_path = data.dbweb.sqlite_path;
    if (data?.metabase) applyMetabasePublic(data.metabase);
    if (data?.status?.raw) Object.assign(status.raw, data.status.raw);
    if (data?.status?.dwh) Object.assign(status.dwh, data.status.dwh);
    if (data?.status?.defect) Object.assign(status.defect, data.status.defect);
    if (data?.status?.dbweb) Object.assign(status.dbweb, data.status.dbweb);
    if (data?.status?.metabase) Object.assign(status.metabase, data.status.metabase);
    ElMessage.success("已保存");
  } catch (error) {
    ElMessage.error(backendErrorHint(error));
  } finally {
    saving.value = false;
  }
}

function openMetabase() {
  window.open(metabaseUrl.value, "_blank");
}

onMounted(load);
</script>

<template>
  <div class="conn-page" v-loading="loading">
    <el-alert
      v-if="backendHint"
      class="mb-4"
      type="warning"
      :closable="false"
      :title="backendHint"
    />
    <div class="conn-grid">
      <article
        v-for="item in CARDS"
        :key="item.key"
        class="conn-card"
        :class="{ 'is-live': status[item.key].ok }"
      >
        <header class="conn-head">
          <div class="conn-head__text">
            <h2>{{ item.title }}</h2>
            <p>{{ endpoint(item.key) }}</p>
          </div>
          <span
            class="conn-pill"
            :class="status[item.key].ok ? 'is-on' : 'is-off'"
          >
            {{ status[item.key].ok ? "已连通" : "未连通" }}
          </span>
        </header>
        <el-form class="conn-form" label-position="top">
          <div class="conn-row">
            <el-form-item label="主机">
              <el-input v-model="form[item.key].host" />
            </el-form-item>
            <el-form-item label="端口">
              <el-input-number
                v-model="form[item.key].port"
                :min="1"
                :max="65535"
                :controls="false"
              />
            </el-form-item>
          </div>
          <el-form-item label="数据库">
            <el-input v-model="form[item.key].database" />
          </el-form-item>
          <div class="conn-row">
            <el-form-item label="用户">
              <el-input v-model="form[item.key].username" />
            </el-form-item>
            <el-form-item label="密码">
              <el-input
                v-model="form[item.key].password"
                type="password"
                show-password
                :placeholder="passwordSet[item.key] ? '已保存' : ''"
                autocomplete="new-password"
              />
            </el-form-item>
          </div>
        </el-form>
        <footer class="conn-foot">
          <el-button
            :loading="testing === item.key"
            @click="onTest(item.key)"
          >
            测试连接
          </el-button>
        </footer>
      </article>

      <article class="conn-card" :class="{ 'is-live': status.dbweb.ok }">
        <header class="conn-head">
          <div class="conn-head__text">
            <h2>Adminer 数据浏览</h2>
            <p>{{ dbwebEndpoint }}</p>
          </div>
          <span
            class="conn-pill"
            :class="status.dbweb.ok ? 'is-on' : 'is-off'"
          >
            {{ status.dbweb.ok ? "已连通" : "未连通" }}
          </span>
        </header>
        <el-form class="conn-form" label-position="top">
          <div class="conn-row">
            <el-form-item label="主机">
              <el-input v-model="dbweb.host" />
            </el-form-item>
            <el-form-item label="端口">
              <el-input-number
                v-model="dbweb.port"
                :min="1"
                :max="65535"
                :controls="false"
              />
            </el-form-item>
          </div>
          <el-form-item label="数据库">
            <el-input
              v-model="dbweb.sqlite_path"
              placeholder="/data/meta/lim_meta.sqlite"
            />
          </el-form-item>
          <div class="conn-row">
            <el-form-item label="协议">
              <el-select v-model="dbweb.scheme">
                <el-option label="http" value="http" />
                <el-option label="https" value="https" />
              </el-select>
            </el-form-item>
            <el-form-item label="服务">
              <el-input model-value="Adminer" disabled />
            </el-form-item>
          </div>
        </el-form>
        <footer class="conn-foot">
          <el-button :loading="testing === 'dbweb'" @click="onTestDbweb">
            测试连接
          </el-button>
        </footer>
      </article>

      <article class="conn-card" :class="{ 'is-live': status.metabase.ok }">
        <header class="conn-head">
          <div class="conn-head__text">
            <h2>Metabase 数据看板</h2>
            <p>{{ metabaseUrl }}</p>
          </div>
          <span
            class="conn-pill"
            :class="status.metabase.ok ? 'is-on' : 'is-off'"
          >
            {{ status.metabase.ok ? "已连通" : "未连通" }}
          </span>
        </header>
        <el-form class="conn-form" label-position="top">
          <div class="conn-row">
            <el-form-item label="主机">
              <el-input v-model="metabase.host" />
            </el-form-item>
            <el-form-item label="端口">
              <el-input-number
                v-model="metabase.port"
                :min="1"
                :max="65535"
                :controls="false"
              />
            </el-form-item>
          </div>
          <div class="conn-row is-equal">
            <el-form-item label="用户">
              <el-input
                v-model="metabase.username"
                placeholder="邮箱或用户名"
                autocomplete="username"
              />
            </el-form-item>
            <el-form-item label="密码">
              <el-input
                v-model="metabase.password"
                type="password"
                show-password
                :placeholder="passwordSet.metabase ? '已保存' : ''"
                autocomplete="new-password"
              />
            </el-form-item>
          </div>
          <el-form-item label="协议">
            <el-select v-model="metabase.scheme">
              <el-option label="http" value="http" />
              <el-option label="https" value="https" />
            </el-select>
          </el-form-item>
        </el-form>
        <footer class="conn-foot">
          <el-button :loading="testing === 'metabase'" @click="onTestMetabase">
            测试连接
          </el-button>
        </footer>
      </article>
    </div>
    <div class="conn-bar">
      <el-button @click="router.push('/feature/db-browser')">
        打开数据浏览
      </el-button>
      <el-button @click="openMetabase">
        打开 Metabase
      </el-button>
      <el-button type="primary" :loading="saving" @click="onSave">
        保存
      </el-button>
    </div>
  </div>
</template>

<style scoped>
.conn-page {
  padding: 20px 24px 28px;
}

.conn-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 20px;
}

.conn-card {
  display: flex;
  flex-direction: column;
  min-height: 100%;
  padding: 22px 22px 18px;
  border: 1px solid var(--el-border-color);
  border-radius: 14px;
  background: var(--el-bg-color);
}

.conn-card.is-live {
  border-color: color-mix(in srgb, var(--el-color-success) 45%, var(--el-border-color));
}

.conn-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 20px;
}

.conn-head__text h2 {
  margin: 0;
  color: var(--el-text-color-primary);
  font-size: 17px;
  font-weight: 650;
  letter-spacing: -0.02em;
  line-height: 1.3;
}

.conn-head__text p {
  margin: 6px 0 0;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  line-height: 1.4;
  word-break: break-all;
}

.conn-pill {
  flex-shrink: 0;
  padding: 3px 9px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  line-height: 1.4;
}

.conn-pill.is-on {
  background: color-mix(in srgb, var(--el-color-success) 14%, transparent);
  color: var(--el-color-success);
}

.conn-pill.is-off {
  background: var(--el-fill-color);
  color: var(--el-text-color-secondary);
}

.conn-form {
  flex: 1;
}

.conn-form :deep(.el-form-item) {
  margin-bottom: 14px;
}

.conn-form :deep(.el-form-item__label) {
  margin-bottom: 4px !important;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.2;
}

.conn-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 120px;
  gap: 12px;
}

.conn-row:last-of-type,
.conn-row.is-equal {
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
}

.conn-form :deep(.el-input-number),
.conn-form :deep(.el-select) {
  width: 100%;
}

.conn-foot {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding-top: 6px;
  border-top: 1px solid var(--el-border-color-lighter);
}

.conn-bar {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 20px;
}

@media (max-width: 960px) {
  .conn-grid {
    grid-template-columns: 1fr;
  }
}
</style>
