<script setup lang="ts">
import { useBoolean } from "../../hooks/useBoolean";
import SearchModal from "./components/SearchModal.vue";

const { bool: show, toggle } = useBoolean();
function handleSearch() {
  toggle();
}
</script>

<template>
  <div>
    <div
      class="search-container w-9 h-[var(--la-chrome-nav)] flex-c cursor-pointer navbar-bg-hover"
      @click="handleSearch"
    >
      <IconifyIconOffline icon="ri/search-line" />
    </div>
    <SearchModal v-model:value="show" />
  </div>
</template>
