<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { ElMessage } from "element-plus";
import {
  deleteManualNotice,
  listManualNotices,
  sendManualNotice,
  type ManualNotice
} from "@/api/modules/defect";
import { listPersons, type PersonItem } from "@/api/modules/persons";
import { backendErrorHint } from "@/api/http";

defineOptions({
  name: "DefectManual"
});

type RecipientDraft = {
  key: number;
  personId: number | string | null;
  department: string;
  name: string;
  phone: string;
};

let draftKey = 1;
let loadAbort: AbortController | null = null;

const loading = ref(false);
const sending = ref(false);
const hint = ref("");
const departments = ref<string[]>([]);
const persons = ref<PersonItem[]>([]);
const fromDept = ref("");
const topic = ref("");
const body = ref("");
const recipients = ref<RecipientDraft[]>([blankRecipient()]);
const notices = ref<ManualNotice[]>([]);
const activeId = ref<number | null>(null);

function blankRecipient(): RecipientDraft {
  return { key: draftKey++, personId: null, department: "", name: "", phone: "" };
}

function personsFor(row: RecipientDraft) {
  const dept = row.department.trim();
  if (!dept) return persons.value;
  return persons.value.filter(
    item => !item.department || item.department === dept
  );
}

function applyPerson(row: RecipientDraft, value: string | number | null) {
  if (value == null || value === "") {
    row.personId = null;
    row.name = "";
    row.phone = "";
    return;
  }
  if (typeof value === "number") {
    const person = persons.value.find(item => item.id === value);
    if (!person) return;
    row.personId = person.id;
    row.name = person.name;
    row.phone = person.phone || "";
    if (person.department) row.department = person.department;
    return;
  }
  row.personId = String(value).trim();
  row.name = String(value).trim();
}

function onDepartmentChange(row: RecipientDraft) {
  if (!row.personId) return;
  const person = persons.value.find(item => item.id === row.personId);
  if (person && person.department && person.department !== row.department) {
    row.personId = null;
  }
}

function addRecipient() {
  recipients.value = [...recipients.value, blankRecipient()];
}

function removeRecipient(key: number) {
  const next = recipients.value.filter(row => row.key !== key);
  recipients.value = next.length ? next : [blankRecipient()];
}

const filledRecipients = computed(() =>
  recipients.value
    .map(row => ({
      department: row.department.trim(),
      name: row.name.trim(),
      phone: row.phone.trim()
    }))
    .filter(row => row.department || row.name || row.phone)
);

const canSend = computed(
  () =>
    filledRecipients.value.length > 0 &&
    Boolean(topic.value.trim() || body.value.trim())
);

const activeNotice = computed(
  () => notices.value.find(row => row.id === activeId.value) || null
);

function recipientLine(row: { department: string; name: string; phone: string }) {
  return [row.department, row.name, row.phone].filter(Boolean).join(" ");
}

function resetForm() {
  topic.value = "";
  body.value = "";
  recipients.value = [blankRecipient()];
  activeId.value = null;
}

async function send() {
  if (!filledRecipients.value.length) {
    ElMessage.warning("请填写接收部门或人员");
    return;
  }
  if (!topic.value.trim() && !body.value.trim()) {
    ElMessage.warning("请填写事项或正文");
    return;
  }
  sending.value = true;
  try {
    const res = await sendManualNotice({
      from_dept: fromDept.value.trim(),
      topic: topic.value.trim(),
      body: body.value.trim(),
      recipients: filledRecipients.value
    });
    const saved = res?.data;
    if (saved) {
      notices.value = [saved, ...notices.value.filter(row => row.id !== saved.id)];
      activeId.value = saved.id;
    }
    ElMessage.success("已发送");
    resetForm();
  } catch (error) {
    ElMessage.error(backendErrorHint(error));
  } finally {
    sending.value = false;
  }
}

async function removeNotice(row: ManualNotice) {
  try {
    await deleteManualNotice(row.id);
    notices.value = notices.value.filter(item => item.id !== row.id);
    if (activeId.value === row.id) activeId.value = null;
  } catch (error) {
    ElMessage.error(backendErrorHint(error));
  }
}

async function load() {
  loadAbort?.abort();
  loadAbort = new AbortController();
  const signal = loadAbort.signal;
  loading.value = true;
  hint.value = "";
  try {
    const [noticeRes, personRes] = await Promise.all([
      listManualNotices(signal),
      listPersons()
    ]);
    notices.value = noticeRes?.data?.notices || [];
    persons.value = personRes?.data?.persons || [];
    departments.value = personRes?.data?.options?.departments || [];
  } catch (error) {
    hint.value = backendErrorHint(error);
  } finally {
    loading.value = false;
  }
}

onMounted(() => load());
onUnmounted(() => loadAbort?.abort());
</script>

<template>
  <div class="manual-page" v-loading="loading">
    <header class="manual-head">
      <div class="manual-head__lead">
        <strong>人工通知</strong>
        <span>部门之间自由沟通，写好直接发送</span>
      </div>
      <div class="manual-actions">
        <el-button @click="resetForm">新建</el-button>
      </div>
    </header>

    <p v-if="hint" class="manual-banner">{{ hint }}</p>

    <section class="sheet">
      <div class="sheet-block">
        <div class="sheet-block__head">
          <strong>通知人员</strong>
          <span>从通讯录选择，也可手填</span>
          <button type="button" class="sheet-add" @click="addRecipient">添加人员</button>
        </div>
        <div class="to-head">
          <span>部门</span>
          <span>姓名</span>
          <span>电话</span>
          <span></span>
        </div>
        <div class="to-list">
          <div v-for="row in recipients" :key="row.key" class="to-row">
            <el-select
              v-model="row.department"
              filterable
              allow-create
              default-first-option
              clearable
              placeholder="选择或输入部门"
              @change="onDepartmentChange(row)"
            >
              <el-option
                v-for="item in departments"
                :key="item"
                :label="item"
                :value="item"
              />
            </el-select>
            <el-select
              v-model="row.personId"
              filterable
              allow-create
              default-first-option
              clearable
              placeholder="姓名"
              @change="value => applyPerson(row, value)"
            >
              <el-option
                v-for="item in personsFor(row)"
                :key="item.id"
                :label="item.name"
                :value="item.id"
              />
            </el-select>
            <el-input v-model="row.phone" placeholder="电话" />
            <button type="button" class="to-remove" @click="removeRecipient(row.key)">
              删除
            </button>
          </div>
        </div>
      </div>

      <div class="sheet-block">
        <div class="sheet-block__head">
          <strong>通知内容</strong>
          <span>事项和正文按实际沟通写</span>
        </div>
        <div class="compose">
          <label class="field is-dept">
            <span>本方部门</span>
            <el-select
              v-model="fromDept"
              filterable
              allow-create
              default-first-option
              clearable
              placeholder="选填"
            >
              <el-option
                v-for="item in departments"
                :key="item"
                :label="item"
                :value="item"
              />
            </el-select>
          </label>
          <label class="field is-topic">
            <span>事项</span>
            <el-input
              v-model="topic"
              placeholder="例如：换模协助、来料确认、点检配合"
            />
          </label>
          <label class="field is-body">
            <span>正文</span>
            <el-input
              v-model="body"
              type="textarea"
              :autosize="{ minRows: 7, maxRows: 16 }"
              placeholder="时间、机台、问题，以及需要对方完成的事项"
            />
          </label>
        </div>
        <div class="compose-actions">
          <el-button
            type="primary"
            :loading="sending"
            :disabled="!canSend"
            @click="send"
          >
            发送
          </el-button>
        </div>
      </div>
    </section>

    <section class="sheet">
      <div class="sheet-block__head">
        <strong>已发送</strong>
        <span>{{ notices.length }} 条</span>
      </div>
      <p v-if="!notices.length" class="empty">还没有发出过通知</p>
      <div v-else class="archive">
        <div class="archive-list">
          <button
            v-for="row in notices"
            :key="row.id"
            type="button"
            class="archive-item"
            :class="{ 'is-active': activeId === row.id }"
            @click="activeId = row.id"
          >
            <strong>{{ row.topic || "部门沟通" }}</strong>
            <em>{{ row.created_at }}</em>
            <span>{{ row.recipients.map(recipientLine).join("、") }}</span>
          </button>
        </div>
        <article v-if="activeNotice" class="archive-read">
          <header>
            <div>
              <strong>{{ activeNotice.topic }}</strong>
              <span>{{ activeNotice.created_at }}</span>
            </div>
            <button type="button" class="to-remove" @click="removeNotice(activeNotice)">
              删除
            </button>
          </header>
          <p v-if="activeNotice.from_dept">本方 {{ activeNotice.from_dept }}</p>
          <p>通知 {{ activeNotice.recipients.map(recipientLine).join("、") }}</p>
          <pre>{{ activeNotice.body || "无正文" }}</pre>
        </article>
        <p v-else class="empty">点左侧一条查看全文</p>
      </div>
    </section>
  </div>
</template>

<style scoped>
.manual-page {
  display: flex;
  flex-direction: column;
  gap: 14px;
  box-sizing: border-box;
  min-height: calc(100vh - var(--la-chrome-total));
  margin: 0 !important;
  padding: 12px 16px 16px;
  background: #eef7fb;
}

.manual-head {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 14px 16px;
  background: #fff;
  border: 1px solid #d5ddd8;
  border-radius: 10px;
}

.manual-head__lead {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.manual-head__lead strong {
  color: #0c3f56;
  font-size: 16px;
  font-weight: 700;
  letter-spacing: -0.02em;
}

.manual-head__lead span {
  color: #5b6b63;
  font-size: 12px;
}

.manual-actions {
  display: flex;
  gap: 8px;
}

.manual-banner {
  margin: 0;
  padding: 8px 12px;
  color: #92400e;
  background: #fffbeb;
  border: 1px solid #f0d48a;
  border-radius: 8px;
  font-size: 13px;
}

.sheet {
  background: #fff;
  border: 1px solid #d5ddd8;
  border-radius: 10px;
  overflow: hidden;
}

.sheet-block + .sheet-block {
  border-top: 1px solid #e7eee9;
}

.sheet-block__head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px 0;
}

.sheet-block__head strong {
  color: #0c3f56;
  font-size: 14px;
  font-weight: 700;
}

.sheet-block__head span {
  color: #6b7c74;
  font-size: 12px;
}

.sheet-add {
  margin-left: auto;
  padding: 0;
  border: 0;
  background: none;
  color: #1e4e79;
  font-size: 13px;
  font-weight: 650;
  cursor: pointer;
}

.sheet-add:hover {
  color: #163c5c;
}

.to-head,
.to-row {
  display: grid;
  grid-template-columns: minmax(160px, 1.2fr) minmax(120px, 0.8fr) minmax(140px, 0.8fr) 48px;
  gap: 8px;
  align-items: center;
}

.to-head {
  margin: 10px 16px 0;
  padding: 0 2px 6px;
  color: #6b7c74;
  font-size: 12px;
  border-bottom: 1px solid #e7eee9;
}

.to-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px 16px 14px;
}

.to-remove {
  padding: 0;
  border: 0;
  background: none;
  color: #b42318;
  font-size: 12px;
  cursor: pointer;
}

.to-remove:hover {
  color: #912018;
}

.compose {
  display: grid;
  grid-template-columns: 200px minmax(0, 1fr);
  gap: 12px;
  padding: 12px 16px 0;
}

.compose-actions {
  display: flex;
  justify-content: flex-end;
  padding: 12px 16px 16px;
}

.compose-actions :deep(.el-button--primary) {
  --el-button-bg-color: #1e4e79;
  --el-button-border-color: #1e4e79;
  --el-button-hover-bg-color: #163c5c;
  --el-button-hover-border-color: #163c5c;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  color: #4d5d56;
  font-size: 12px;
}

.field.is-body {
  grid-column: 1 / -1;
}

.field :deep(.el-textarea__inner) {
  line-height: 1.55;
}

.empty {
  margin: 0;
  padding: 36px 16px;
  color: #6b7c74;
  font-size: 13px;
  text-align: center;
}

.archive {
  display: grid;
  grid-template-columns: minmax(240px, 300px) minmax(0, 1fr);
  min-height: 240px;
  margin-top: 10px;
  border-top: 1px solid #e7eee9;
}

.archive-list {
  display: flex;
  flex-direction: column;
  max-height: 340px;
  overflow: auto;
  background: #f7faf8;
}

.archive-item {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 2px 8px;
  padding: 12px 14px;
  border: 0;
  border-bottom: 1px solid #e7eee9;
  background: transparent;
  text-align: left;
  cursor: pointer;
}

.archive-item:hover,
.archive-item.is-active {
  background: #fff;
}

.archive-item strong {
  color: #0c3f56;
  font-size: 13px;
  font-weight: 700;
}

.archive-item em {
  color: #6b7c74;
  font-size: 12px;
  font-style: normal;
  font-variant-numeric: tabular-nums;
}

.archive-item span {
  grid-column: 1 / -1;
  overflow: hidden;
  color: #5b6b63;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.archive-read {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 16px 18px;
}

.archive-read header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.archive-read header strong {
  display: block;
  color: #0c3f56;
  font-size: 16px;
}

.archive-read header span,
.archive-read p {
  margin: 0;
  color: #5b6b63;
  font-size: 12px;
}

.archive-read pre {
  margin: 4px 0 0;
  padding: 12px 14px;
  color: #1f2937;
  background: #f7faf8;
  border-radius: 8px;
  font-family: "Microsoft YaHei", Calibri, "Segoe UI", sans-serif;
  font-size: 13px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}

@media (max-width: 900px) {
  .to-head,
  .to-row,
  .compose,
  .archive {
    grid-template-columns: 1fr;
  }

  .to-head {
    display: none;
  }
}
</style>
