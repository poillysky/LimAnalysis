import { addIcon } from "@iconify/vue/dist/offline";
import { getSvgInfo } from "@pureadmin/utils";
import epIcons from "@iconify/json/json/ep.json";
import riIcons from "@iconify/json/json/ri.json";

import RiSearchLine from "~icons/ri/search-line?raw";
import RiInformationLine from "~icons/ri/information-line?raw";

const EP_WIDTH = (epIcons as { width?: number }).width ?? 1024;
const RI_WIDTH = (riIcons as { width?: number }).width ?? 24;

function addEpIcon(name: string) {
  const icon = (epIcons as { icons: Record<string, { body: string }> }).icons[
    name
  ];
  if (!icon) return;
  addIcon(`ep/${name}`, {
    body: icon.body,
    width: EP_WIDTH,
    height: EP_WIDTH
  });
}

function addRiIcon(name: string) {
  const icon = (riIcons as { icons: Record<string, { body: string }> }).icons[
    name
  ];
  if (!icon) return;
  const data = {
    body: icon.body,
    width: RI_WIDTH,
    height: RI_WIDTH
  };
  addIcon(`ri/${name}`, data);
  addIcon(`ri:${name}`, data);
}

/** Element Plus — keep a small set for non-menu usages */
[
  "home-filled",
  "warn-triangle-filled",
  "histogram",
  "trend-charts",
  "circle-check-filled",
  "document-checked",
  "grid",
  "operation",
  "setting",
  "search",
  "user",
  "user-filled",
  "avatar",
  "postcard",
  "notebook",
  "folder-opened",
  "link",
  "connection",
  "download",
  "aim",
  "document",
  "coin",
  "data-board",
  "monitor",
  "data-analysis",
  "brush",
  "cpu"
].forEach(addEpIcon);

/**
 * Remix — 侧栏一级 fill、二级 line，以及页面内按钮用到的图标。
 */
[
  "home-fill",
  "home-smile-2-fill",
  "dashboard-fill",
  "dashboard-2-fill",
  "line-chart-fill",
  "file-check-fill",
  "notification-3-fill",
  "megaphone-fill",
  "camera-fill",
  "image-2-fill",
  "qr-scan-2-fill",
  "settings-3-fill",
  "equalizer-fill",
  "dashboard-line",
  "pulse-line",
  "search-line",
  "grid-line",
  "layout-grid-line",
  "table-line",
  "user-3-line",
  "contacts-line",
  "team-line",
  "calendar-schedule-line",
  "calendar-check-line",
  "folder-open-line",
  "folder-3-line",
  "folder-image-line",
  "hard-drive-2-line",
  "arrow-go-back-line",
  "arrow-down-s-line",
  "arrow-right-s-line",
  "close-line",
  "add-line",
  "qr-scan-2-line",
  "link",
  "links-line",
  "database-2-line",
  "focus-3-line",
  "radar-line",
  "brush-line",
  "brush-3-line",
  "pie-chart-line",
  "pie-chart-2-line",
  "cpu-line",
  "robot-2-line",
  "camera-line",
  "file-list-3-line",
  "list-check-3",
  "price-tag-3-line",
  "image-line",
  "eye-line",
  "eye-2-line",
  "qr-scan-line",
  "barcode-line",
  "barcode-box-line",
  "upload-2-line",
  "image-add-line",
  "file-text-line",
  "alarm-warning-line",
  "chat-1-line",
  "chat-smile-3-line",
  "information-line"
].forEach(addRiIcon);

[
  ["ri/search-line", RiSearchLine],
  ["ri/information-line", RiInformationLine]
].forEach(([name, icon]) => {
  addIcon(name as string, getSvgInfo(icon as string));
});
