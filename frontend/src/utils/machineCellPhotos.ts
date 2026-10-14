/**
 * LIM / 本体交叉表 / 通知中心共用看图取数口径。
 * - LIM：机台×模穴；本体：本体号（模具位+穴位位，如 A1）
 * - 日期：ServerTime 生产日；默认当天（无图提示「当日无图片」）
 * - 列表：order=desc，ServerTime 最新优先
 * - 外观视角：带数量，默认选中数量最多的视角
 */
import {
  getAppearanceViewCounts,
  getViewerDates,
  getViewerImages,
  type AppearanceViewCount,
  type InspectionImage,
  type PhotoSource
} from "@/api/modules/inspection";

export type PhotoDateMeta = {
  dates: string[];
  today: string;
  defaultDate: string;
};

export type PhotoCameraOption = {
  value: string;
  label: string;
  count: number;
};

function formatDateLabel(ymd: string) {
  const s = String(ymd || "").trim();
  if (s.length === 8 && /^\d{8}$/.test(s)) {
    return `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}`;
  }
  return s;
}

export function photoDateLabel(ymd: string) {
  return formatDateLabel(ymd);
}

/** 拉取日期列表；默认日固定当天（后端已保证 dates 含 today） */
export async function fetchCellPhotoDates(params: {
  projectId: string;
  source: PhotoSource;
  machine?: string;
  camera?: string;
  /** 本体号如 A1 */
  body?: string;
}): Promise<PhotoDateMeta> {
  const { projectId, source } = params;
  const body = String(params.body || "").trim().toUpperCase();
  const machine = String(params.machine || "").trim();
  const res = await getViewerDates(
    projectId,
    body ? "" : machine,
    source,
    source === "appearance" && !body ? params.camera || "" : "",
    source === "appearance" ? "mold" : "tester",
    body
  );
  const data = res?.data;
  const today = String(data?.today || "").trim();
  let dates = [...(data?.dates || [])];
  if (today && !dates.includes(today)) dates = [today, ...dates];
  const defaultDate = today || data?.default_date || dates[0] || "";
  return { dates, today, defaultDate };
}

/** 空列表提示：选中当天固定「当日无图片」 */
export function emptyPhotoHint(
  date: string,
  today: string,
  apiHint?: string
): string {
  if (today && date === today) return "当日无图片";
  return apiHint || "这一天没有找到图片";
}

/** 外观视角 + 数量，标签形如 `CamA（12）` */
export async function fetchAppearanceCameraOptions(params: {
  projectId: string;
  date: string;
  machine?: string;
  cavity?: string;
  body?: string;
  dim?: "mold" | "tester";
}): Promise<PhotoCameraOption[]> {
  const body = String(params.body || "").trim().toUpperCase();
  const dim = params.dim || "mold";
  const res = await getAppearanceViewCounts({
    project_id: params.projectId,
    machine: body ? undefined : params.machine,
    cavity: body ? undefined : dim === "mold" ? params.cavity : undefined,
    body: body || undefined,
    date: params.date,
    dim
  });
  const rows: AppearanceViewCount[] = res?.data?.cameras || [];
  return rows.map(item => {
    const name = String(item.camera || "").trim();
    const count = Number(item.count || 0);
    return {
      value: name,
      label: `${name}（${count}）`,
      count
    };
  });
}

/** 取图：统一 ServerTime 最新优先 */
export async function fetchCellPhotos(params: {
  projectId: string;
  date: string;
  source: PhotoSource;
  machine?: string;
  cavity?: string;
  body?: string;
  camera?: string;
}): Promise<{ images: InspectionImage[]; hint?: string }> {
  const { projectId, date, source } = params;
  const body = String(params.body || "").trim().toUpperCase();
  const machine = String(params.machine || "").trim();
  const cavity = String(params.cavity || "").trim().toUpperCase();
  if (!projectId || !date) {
    return { images: [], hint: "缺少日期" };
  }
  if (body) {
    if (source === "appearance") {
      const camera = String(params.camera || "").trim();
      if (!camera) return { images: [], hint: "没有可用视角" };
      const res = await getViewerImages({
        project_id: projectId,
        body,
        date,
        source: "appearance",
        camera,
        order: "desc"
      });
      return {
        images: res?.data?.images || [],
        hint: res?.data?.hint
      };
    }
    const res = await getViewerImages({
      project_id: projectId,
      body,
      date,
      status: "OK",
      source: "mold",
      order: "desc"
    });
    return {
      images: res?.data?.images || [],
      hint: res?.data?.hint
    };
  }
  if (!machine || !cavity) {
    return { images: [], hint: "缺少机台、模穴或日期" };
  }
  if (source === "appearance") {
    const camera = String(params.camera || "").trim();
    if (!camera) return { images: [], hint: "没有可用视角" };
    const res = await getViewerImages({
      project_id: projectId,
      machine,
      cavity,
      date,
      source: "appearance",
      dim: "mold",
      camera,
      order: "desc"
    });
    return {
      images: res?.data?.images || [],
      hint: res?.data?.hint
    };
  }
  const res = await getViewerImages({
    project_id: projectId,
    machine,
    cavity,
    date,
    status: "OK",
    source: "mold",
    order: "desc"
  });
  return {
    images: res?.data?.images || [],
    hint: res?.data?.hint
  };
}

/**
 * 默认选数量最多的视角。
 * keepCurrent=true 时仅在用户刚选手动切换后保留（一般日期/穴位变更不传）。
 */
export function pickCameraValue(
  options: PhotoCameraOption[],
  current = "",
  keepCurrent = false
): string {
  if (!options.length) return "";
  if (
    keepCurrent &&
    current &&
    options.some(item => item.value === current)
  ) {
    return current;
  }
  let best = options[0];
  for (const item of options) {
    if (item.count > best.count) best = item;
  }
  return best.value;
}
