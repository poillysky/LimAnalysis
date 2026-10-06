<script setup lang="ts">
import Motion from "./utils/motion";
import { useRouter } from "vue-router";
import { message } from "@/utils/message";
import { loginRules } from "./utils/rule";
import { ref, reactive, toRaw } from "vue";
import { debounce } from "@pureadmin/utils";
import { useNav } from "@/layout/hooks/useNav";
import { useEventListener } from "@vueuse/core";
import type { FormInstance } from "element-plus";
import { useLayout } from "@/layout/hooks/useLayout";
import { useUserStoreHook } from "@/store/modules/user";
import { initRouter, getTopMenu } from "@/router/utils";
import { bg, illustration } from "./utils/static";
import { useRenderIcon } from "@/components/ReIcon/src/hooks";
import { useDataThemeChange } from "@/layout/hooks/useDataThemeChange";

import dayIcon from "@/assets/svg/day.svg?component";
import darkIcon from "@/assets/svg/dark.svg?component";
import Lock from "~icons/ri/lock-fill";
import User from "~icons/ri/user-3-fill";

defineOptions({
  name: "Login"
});

const router = useRouter();
const loading = ref(false);
const disabled = ref(false);
const ruleFormRef = ref<FormInstance>();

const { initStorage } = useLayout();
initStorage();

const { dataTheme, overallStyle, dataThemeChange } = useDataThemeChange();
dataThemeChange(overallStyle.value);
const { title } = useNav();

const ruleForm = reactive({
  username: "admin",
  password: "admin123"
});

const onLogin = async (formEl: FormInstance | undefined) => {
  if (!formEl) return;
  await formEl.validate(valid => {
    if (valid) {
      loading.value = true;
      useUserStoreHook()
        .loginByUsername({
          username: ruleForm.username,
          password: ruleForm.password
        })
        .then(res => {
          if (res.success) {
            return initRouter().then(() => {
              disabled.value = true;
              const homePath = getTopMenu(true)?.path || "/welcome";
              router
                .push(homePath)
                .then(() => {
                  message("登录成功", { type: "success" });
                })
                .finally(() => (disabled.value = false));
            });
          } else {
            message(res.message || "登录失败", { type: "error" });
          }
        })
        .catch(error => {
          const msg =
            error?.response?.data?.message || "登录失败，请检查账号密码或后端是否启动";
          message(msg, { type: "error" });
        })
        .finally(() => (loading.value = false));
    }
  });
};

const immediateDebounce: any = debounce(
  formRef => onLogin(formRef),
  1000,
  true
);

useEventListener(document, "keydown", ({ code }) => {
  if (
    ["Enter", "NumpadEnter"].includes(code) &&
    !disabled.value &&
    !loading.value
  )
    immediateDebounce(ruleFormRef.value);
});
</script>

<template>
  <div class="login-page select-none">
    <img :src="bg" class="login-wave" alt="" />
    <div class="login-theme">
      <el-switch
        v-model="dataTheme"
        inline-prompt
        :active-icon="dayIcon"
        :inactive-icon="darkIcon"
        @change="dataThemeChange"
      />
    </div>

    <aside class="login-stage">
      <p class="login-brand">{{ title }}</p>
      <div class="login-stage__art">
        <component :is="toRaw(illustration)" />
      </div>
    </aside>

    <main class="login-panel">
      <div class="login-panel__inner">
        <header class="login-lockup">
          <p class="login-lead">产线质量分析</p>
        </header>
        <div class="login-form">
          <h1>登录</h1>
          <el-form
          ref="ruleFormRef"
          :model="ruleForm"
          :rules="loginRules"
          size="large"
          label-position="top"
          @submit.prevent
        >
          <Motion :delay="40">
            <el-form-item
              label="账号"
              :rules="[
                {
                  required: true,
                  message: '请输入账号',
                  trigger: 'blur'
                }
              ]"
              prop="username"
            >
              <el-input
                v-model="ruleForm.username"
                clearable
                placeholder="输入账号"
                :prefix-icon="useRenderIcon(User)"
              />
            </el-form-item>
          </Motion>

          <Motion :delay="90">
            <el-form-item label="密码" prop="password">
              <el-input
                v-model="ruleForm.password"
                clearable
                show-password
                placeholder="输入密码"
                :prefix-icon="useRenderIcon(Lock)"
              />
            </el-form-item>
          </Motion>

          <Motion :delay="140">
            <el-button
              class="login-submit"
              native-type="button"
              :loading="loading"
              :disabled="disabled"
              @click="onLogin(ruleFormRef)"
            >
              登录
            </el-button>
          </Motion>
        </el-form>
        </div>
      </div>
    </main>
  </div>
</template>

<style scoped>
@import url("@/style/login.css");

.login-form :deep(.el-form-item) {
  margin-bottom: 18px;
}

.login-form :deep(.el-form-item__label) {
  margin-bottom: 6px;
  color: var(--login-ink);
  font-weight: 600;
  line-height: 1.4;
}

.login-form :deep(.el-input__wrapper) {
  padding: 4px 12px;
  background: var(--login-panel);
  box-shadow: 0 0 0 1px var(--login-line);
  transition: box-shadow 160ms var(--login-ease);
}

.login-form :deep(.el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px rgb(47 111 237 / 45%);
}

.login-form :deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 2px var(--login-accent);
}

.login-form :deep(.el-input__inner) {
  height: 42px;
  color: var(--login-ink);
}

.login-form :deep(.login-submit.el-button) {
  width: 100%;
  height: 44px;
  margin-top: 8px;
  border: 0;
  background: var(--login-ink);
  color: #edf2f6;
  font-size: 15px;
  font-weight: 600;
  transition:
    transform 140ms var(--login-ease),
    background-color 160ms ease,
    opacity 160ms ease;
}

html.dark .login-form :deep(.login-submit.el-button) {
  background: var(--login-accent);
  color: #0c1218;
}

.login-form :deep(.login-submit.el-button:hover),
.login-form :deep(.login-submit.el-button:focus-visible) {
  background: color-mix(in srgb, var(--login-ink) 88%, var(--login-accent));
  color: #edf2f6;
}

html.dark .login-form :deep(.login-submit.el-button:hover),
html.dark .login-form :deep(.login-submit.el-button:focus-visible) {
  background: color-mix(in srgb, var(--login-accent) 86%, #fff);
  color: #0c1218;
}

.login-form :deep(.login-submit.el-button:active) {
  transform: scale(0.97);
}

.login-form :deep(.login-submit.el-button.is-disabled),
.login-form :deep(.login-submit.el-button.is-loading) {
  opacity: 0.72;
}
</style>
