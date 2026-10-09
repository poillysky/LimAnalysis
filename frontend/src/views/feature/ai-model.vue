<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import {
  getAiConfig,
  listAiModels,
  saveAiConfig,
  testAiConnection,
  type AiConfig
} from "@/api/modules/ai";
import { backendErrorHint } from "@/api/http";

defineOptions({
  name: "FeatureAiModel"
});

const loading = ref(false);
const saving = ref(false);
const testing = ref(false);
const listing = ref(false);
const form = reactive({
  enabled: false,
  provider: "openai_compatible",
  base_url: "https://api.openai.com/v1",
  model: "gpt-4o-mini",
  timeout_seconds: 45,
  temperature: 0.2,
  api_key: ""
});
const apiKeySet = ref(false);
const ready = ref(false);
const lastTest = ref("");
const modelOptions = ref<string[]>([]);

const statusText = computed(() => {
  if (ready.value) return "已就绪，数据清洗公式将优先用 AI 辅助生成";
  if (form.enabled) return "已启用但未就绪（检查地址 / 模型 / API Key）";
  return "未启用：公式仍用规则生成";
});

const alertType = computed(() =>
  lastTest.value.includes("成功") ? "success" : "warning"
);

function applyConfig(data: AiConfig) {
  form.enabled = !!data.enabled;
  form.provider = data.provider || "openai_compatible";
  form.base_url = data.base_url || "";
  form.model = data.model || "";
  form.timeout_seconds = data.timeout_seconds || 45;
  form.temperature = Number(data.temperature ?? 0.2);
  form.api_key = "";
  apiKeySet.value = !!data.api_key_set;
  ready.value = !!data.ready;
}

async function load() {
  loading.value = true;
  try {
    const res = await getAiConfig();
    applyConfig(res.data);
  } catch (error) {
    ElMessage.error(backendErrorHint(error));
  } finally {
    loading.value = false;
  }
}

async function onSave(silent = false) {
  saving.value = true;
  try {
    const payload: Record<string, unknown> = {
      enabled: form.enabled,
      provider: form.provider,
      base_url: form.base_url.trim(),
      model: form.model.trim(),
      timeout_seconds: form.timeout_seconds,
      temperature: form.temperature
    };
    if (form.api_key.trim()) {
      payload.api_key = form.api_key.trim();
    }
    const res = await saveAiConfig(payload);
    applyConfig(res.data);
    if (!silent) ElMessage.success("已保存 AI 连接配置");
    return true;
  } catch (error) {
    ElMessage.error(backendErrorHint(error));
    return false;
  } finally {
    saving.value = false;
  }
}

async function onClearKey() {
  saving.value = true;
  try {
    const res = await saveAiConfig({ clear_api_key: true });
    applyConfig(res.data);
    ElMessage.success("已清除 API Key");
  } catch (error) {
    ElMessage.error(backendErrorHint(error));
  } finally {
    saving.value = false;
  }
}

async function onTest() {
  testing.value = true;
  lastTest.value = "";
  try {
    const ok = await onSave(true);
    if (!ok) return;
    const res = await testAiConnection();
    lastTest.value = res.data?.reply
      ? `${res.data.message}：${res.data.reply}`
      : res.data?.message || "连接成功";
    ElMessage.success(res.data?.message || "连接成功");
  } catch (error) {
    lastTest.value = backendErrorHint(error);
    ElMessage.error(lastTest.value);
  } finally {
    testing.value = false;
  }
}

async function onListModels() {
  listing.value = true;
  lastTest.value = "";
  try {
    const ok = await onSave(true);
    if (!ok) return;
    const res = await listAiModels();
    modelOptions.value = res.data?.models || [];
    lastTest.value = res.data?.message || `共 ${modelOptions.value.length} 个模型`;
    if (!res.data?.current_found && form.model && modelOptions.value.length) {
      ElMessage.warning(
        `当前模型「${form.model}」不在列表中，请从下拉框改选`
      );
    } else {
      ElMessage.success(lastTest.value);
    }
  } catch (error) {
    lastTest.value = backendErrorHint(error);
    ElMessage.error(lastTest.value);
  } finally {
    listing.value = false;
  }
}

function fillPreset(kind: string) {
  if (kind === "openai") {
    form.base_url = "https://api.openai.com/v1";
    form.model = "gpt-4o-mini";
  } else if (kind === "deepseek") {
    form.base_url = "https://api.deepseek.com/v1";
    form.model = "deepseek-chat";
  } else if (kind === "qwen") {
    form.base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1";
    form.model = "qwen-plus";
  } else if (kind === "ollama") {
    form.base_url = "http://127.0.0.1:11434/v1";
    form.model = "qwen2.5:7b";
    if (!form.api_key && !apiKeySet.value) {
      form.api_key = "ollama";
    }
  }
  modelOptions.value = [];
}

onMounted(load);
</script>

<template>
  <div class="ai-page main-content" v-loading="loading">
    <div class="ai-head">
      <div>
        <h2>AI 模型配置</h2>
        <p>连接 OpenAI 兼容接口，供数据清洗「描述生成」公式辅助使用。</p>
      </div>
      <el-tag
        :type="ready ? 'success' : form.enabled ? 'warning' : 'info'"
      >
        {{ statusText }}
      </el-tag>
    </div>

    <section class="ai-panel">
      <el-form label-width="120px" class="ai-form">
        <el-form-item label="启用 AI">
          <el-switch v-model="form.enabled" />
        </el-form-item>
        <el-form-item label="快捷预设">
          <el-button size="small" @click="fillPreset('openai')">OpenAI</el-button>
          <el-button size="small" @click="fillPreset('deepseek')">DeepSeek</el-button>
          <el-button size="small" @click="fillPreset('qwen')">通义千问</el-button>
          <el-button size="small" @click="fillPreset('ollama')">Ollama 本地</el-button>
        </el-form-item>
        <el-form-item label="接口地址">
          <el-input
            v-model="form.base_url"
            placeholder="https://api.openai.com/v1"
          />
        </el-form-item>
        <el-form-item label="模型名">
          <div class="ai-model-row">
            <el-select
              v-model="form.model"
              filterable
              allow-create
              default-first-option
              placeholder="填写或从列表选择"
              style="flex: 1"
            >
              <el-option
                v-for="m in modelOptions"
                :key="m"
                :label="m"
                :value="m"
              />
            </el-select>
            <el-button :loading="listing" @click="onListModels">
              拉取模型列表
            </el-button>
          </div>
          <p class="ai-hint">
            「Model not found」= 地址/Key 多半已通，但模型名与服务商不一致。点拉取后改选。
          </p>
        </el-form-item>
        <el-form-item label="API Key">
          <div class="ai-key-row">
            <el-input
              v-model="form.api_key"
              type="password"
              show-password
              :placeholder="apiKeySet ? '已保存密钥，留空表示不修改' : '请输入 API Key'"
            />
            <el-button
              v-if="apiKeySet"
              plain
              type="danger"
              :loading="saving"
              @click="onClearKey"
            >
              清除密钥
            </el-button>
          </div>
        </el-form-item>
        <el-form-item label="超时(秒)">
          <el-input-number v-model="form.timeout_seconds" :min="5" :max="180" />
        </el-form-item>
        <el-form-item label="温度">
          <el-input-number
            v-model="form.temperature"
            :min="0"
            :max="2"
            :step="0.1"
            :precision="1"
          />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="saving" @click="onSave()">
            保存
          </el-button>
          <el-button :loading="testing" @click="onTest">测试连接</el-button>
        </el-form-item>
        <el-alert
          v-if="lastTest"
          :type="alertType"
          :closable="false"
          :title="lastTest"
          show-icon
        />
      </el-form>
      <aside class="ai-aside">
        <h3>说明</h3>
        <ul>
          <li>兼容 OpenAI Chat Completions 协议的服务均可。</li>
          <li>模型名必须是该接口真实提供的 id（区分大小写）。</li>
          <li>保存后，数据清洗「公式生成 → AI 描述」优先调用此模型。</li>
          <li>AI 失败或未启用时，自动回退规则生成。</li>
        </ul>
      </aside>
    </section>
  </div>
</template>

<style scoped>
.ai-page {
  padding: var(--la-page-pad-y) var(--la-page-pad-x) var(--la-space-xl);
}

.ai-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--la-space-md);
  margin-bottom: var(--la-space-lg);
}

.ai-head h2 {
  margin: 0 0 2px;
  font-size: var(--la-page-title);
  font-weight: 650;
}

.ai-head p {
  margin: 0;
  color: var(--el-text-color-secondary);
  font-size: var(--la-page-desc);
}

.ai-panel {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 280px;
  gap: 20px;
  padding: 20px 22px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 12px;
  background: var(--el-bg-color);
}

.ai-form {
  max-width: 640px;
}

.ai-key-row,
.ai-model-row {
  display: flex;
  gap: 8px;
  width: 100%;
}

.ai-hint {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.5;
}

.ai-aside h3 {
  margin: 0 0 10px;
  font-size: 15px;
}

.ai-aside ul {
  margin: 0;
  padding-left: 18px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
  line-height: 1.7;
}

@media (max-width: 960px) {
  .ai-panel {
    grid-template-columns: 1fr;
  }
}
</style>
