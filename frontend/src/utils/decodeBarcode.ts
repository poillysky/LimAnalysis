type Detected = { rawValue?: string };

type Detector = {
  detect: (image: ImageBitmap) => Promise<Detected[]>;
};

function detector(): Detector | null {
  const Ctor = (
    window as Window & {
      BarcodeDetector?: new (options?: { formats?: string[] }) => Detector;
    }
  ).BarcodeDetector;
  if (!Ctor) return null;
  try {
    return new Ctor({
      formats: ["qr_code", "data_matrix", "code_128", "code_39", "ean_13"]
    });
  } catch {
    return new Ctor();
  }
}

export async function recognizeScanFile(file: File): Promise<string> {
  const det = detector();
  if (!det) {
    throw new Error("当前浏览器无法识别图片二维码，请用 Edge 或 Chrome");
  }
  if (!file.type.startsWith("image/")) {
    throw new Error("请上传图片");
  }
  const bitmap = await createImageBitmap(file);
  try {
    const hits = await det.detect(bitmap);
    const value = String(hits[0]?.rawValue || "").trim();
    if (value) return value;
  } finally {
    bitmap.close();
  }
  throw new Error("未识别到二维码");
}
