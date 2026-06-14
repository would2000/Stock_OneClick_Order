import { useEffect, useRef, useState } from "react";
import { Loader2, ShieldCheck, ExternalLink, Eye, EyeOff, FolderOpen } from "lucide-react";
import { login, uploadCert, getRemembered, type LoginEnvironment, type LoginPayload, type LoginState } from "../services/api";

type LoginScreenProps = {
  onLoggedIn: (state: LoginState) => void;
};

const ENVIRONMENTS: { id: LoginEnvironment; label: string; hint: string }[] = [
  { id: "sim", label: "模擬環境", hint: "本機沙盒・無安控・可隨意下單測試" },
  { id: "yuanta", label: "元大帳號", hint: "正式實單環境（需帳號＋憑證）" },
  { id: "sinopac", label: "永豐金帳號", hint: "正式實單環境（需 API Key＋憑證）" }
];

// 永豐金 Shioaji API Key 申請說明
const SINOPAC_APIKEY_URL = "https://www.sinotrade.com.tw/newweb/Main/quote/api/";

// 富果 Fugle MarketData API Key 申請（模擬環境用真實行情）
const FUGLE_APIKEY_URL = "https://developer.fugle.tw/";

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = String(reader.result);
      const comma = result.indexOf(",");
      resolve(comma >= 0 ? result.slice(comma + 1) : result);
    };
    reader.onerror = () => reject(reader.error ?? new Error("讀取檔案失敗"));
    reader.readAsDataURL(file);
  });
}

// 文字/密碼欄位：後方明碼/暗碼切換鈕，下方可選「記住此欄」勾選。
function MaskField({
  label,
  value,
  placeholder,
  defaultMasked = false,
  labelRight,
  onChange,
  rememberKey,
  remembered,
  onRemember
}: {
  label: string;
  value: string;
  placeholder?: string;
  defaultMasked?: boolean;
  labelRight?: React.ReactNode;
  onChange: (value: string) => void;
  rememberKey?: string;
  remembered?: boolean;
  onRemember?: (value: boolean) => void;
}) {
  const [masked, setMasked] = useState(defaultMasked);
  return (
    <div className="loginField">
      <span className="loginLabelRow">{label}{labelRight}</span>
      <span className="loginInputWrap">
        <input
          type={masked ? "password" : "text"}
          value={value}
          placeholder={placeholder}
          autoComplete="off"
          onChange={(event) => onChange(event.target.value)}
        />
        <button
          type="button"
          className="loginEye"
          tabIndex={-1}
          title={masked ? "顯示明碼" : "隱藏為暗碼"}
          onClick={() => setMasked((current) => !current)}
        >
          {masked ? <EyeOff size={14} /> : <Eye size={14} />}
        </button>
      </span>
      {rememberKey ? (
        <label className="loginRemember">
          <input type="checkbox" checked={!!remembered} onChange={(event) => onRemember?.(event.target.checked)} />
          記住{label}{remembered && !value ? "（已記住，留白沿用）" : ""}
        </label>
      ) : null}
    </div>
  );
}

// 憑證欄位：瀏覽檔案 → 上傳 → 取得伺服器路徑（避免手打路徑出錯）。
// currentName＝目前 .env 設定的憑證檔名，讓使用者知道「留白時會用哪一張」。
function CertField({ label, onPath, currentName }: { label: string; onPath: (path: string) => void; currentName?: string }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [filename, setFilename] = useState("");
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");

  async function onPick(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setUploading(true);
    setError("");
    try {
      const base64 = await fileToBase64(file);
      const result = await uploadCert(file.name, base64);
      setFilename(result.filename);
      onPath(result.path);
    } catch (err) {
      setError(err instanceof Error ? err.message : "憑證上傳失敗");
      setFilename("");
      onPath("");
    } finally {
      setUploading(false);
    }
  }

  return (
    <div className="loginField">
      <span className="loginLabelRow">{label}</span>
      <span className="loginCertRow">
        <button type="button" className="loginBrowse" disabled={uploading} onClick={() => inputRef.current?.click()}>
          {uploading ? <Loader2 size={13} className="spin" /> : <FolderOpen size={13} />} 瀏覽…
        </button>
        <span className="loginCertName" title={filename || currentName}>
          {filename
            ? `已選：${filename}`
            : currentName
              ? `目前沿用：${currentName}`
              : "未選擇（留白沿用設定）"}
        </span>
        <input ref={inputRef} type="file" accept=".pfx,.p12" hidden onChange={(event) => void onPick(event)} />
      </span>
      {error ? <span className="loginError">{error}</span> : null}
    </div>
  );
}

export function LoginScreen({ onLoggedIn }: LoginScreenProps) {
  const [env, setEnv] = useState<LoginEnvironment>("sim");
  const [form, setForm] = useState<LoginPayload>({ environment: "sim" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [ack, setAck] = useState(false);
  const [rememberedKeys, setRememberedKeys] = useState<string[]>([]);
  const [certDefaults, setCertDefaults] = useState<{ yuanta: boolean; sinopac: boolean }>({ yuanta: false, sinopac: false });

  // 載入已記住的欄位（目前只有富果金鑰）與 .env 設定的憑證檔名。
  useEffect(() => {
    getRemembered()
      .then((result) => {
        setRememberedKeys(result.fields);
        setCertDefaults(result.certs);
      })
      .catch(() => setRememberedKeys([]));
  }, []);

  function pickEnv(next: LoginEnvironment) {
    setEnv(next);
    setForm({ environment: next });
    setError("");
    setAck(false);
  }

  function setField(key: keyof LoginPayload, value: string) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  async function submit() {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const state = await login({ ...form, environment: env });
      onLoggedIn(state);
    } catch (err) {
      setError(err instanceof Error ? err.message : "登入失敗。");
    } finally {
      setBusy(false);
    }
  }

  const isLive = env === "yuanta" || env === "sinopac";

  return (
    <div className="loginScreen">
      <div className="loginCard">
        <div className="loginBrand">
          <ShieldCheck size={22} />
          <div>
            <strong>自動交易系統</strong>
            <span>請選擇登入環境</span>
          </div>
        </div>

        <div className="loginEnvGrid">
          {ENVIRONMENTS.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`loginEnvOption ${env === item.id ? "active" : ""} ${item.id === "sim" ? "sim" : "live"}`}
              onClick={() => pickEnv(item.id)}
            >
              <strong>{item.label}</strong>
              <span>{item.hint}</span>
            </button>
          ))}
        </div>

        {/* 固定高度區，切換環境時視窗不會上下跳動 */}
        <div className="loginBody">
          <div className="loginFields">
            {env === "sim" ? (
              <>
                <p className="loginNote">模擬環境不需帳號或憑證，登入後可不受限制地測試下單流程（不會送出任何真實委託）。</p>
                <MaskField
                  label="富果 API Key（選填）"
                  value={form.fugle_api_key ?? ""}
                  placeholder={
                    rememberedKeys.includes("fugle_api_key")
                      ? "已儲存，留白沿用（換新金鑰可重填）"
                      : "填入後沙盒改用真實行情；留白則用合成報價"
                  }
                  defaultMasked
                  labelRight={
                    <a href={FUGLE_APIKEY_URL} target="_blank" rel="noreferrer" className="loginExtLink">
                      申請富果 API Key <ExternalLink size={12} />
                    </a>
                  }
                  onChange={(v) => setField("fugle_api_key", v)}
                />
              </>
            ) : null}

            {env === "yuanta" ? (
              <>
                <p className="loginNote">帳號、密碼、憑證密碼由後端 .env 設定（YUANTA_ACCOUNT / PASSWORD / CERT_PASSWORD）。此處僅選擇憑證檔，留白沿用 .env 設定的憑證。</p>
                <CertField label="憑證（.pfx）" onPath={(p) => setField("cert_path", p)} currentName={certDefaults.yuanta ? "已由 .env 設定的憑證" : ""} />
              </>
            ) : null}

            {env === "sinopac" ? (
              <>
                <p className="loginNote">
                  API Key、Secret Key、身分證、憑證密碼由後端 .env 設定（SHIOAJI_*）。此處僅選擇 CA 憑證，留白沿用 .env 設定。
                  <a href={SINOPAC_APIKEY_URL} target="_blank" rel="noreferrer" className="loginExtLink"> 申請 API Key <ExternalLink size={12} /></a>
                </p>
                <CertField label="CA 憑證（.pfx）" onPath={(p) => setField("cert_path", p)} currentName={certDefaults.sinopac ? "已由 .env 設定的憑證" : ""} />
              </>
            ) : null}
          </div>

          <p className={`loginWarn ${isLive ? "" : "hidden"}`}>⚠️ 此為正式實單環境，登入後送出的委託將以真實帳戶成交。</p>
          {isLive ? (
            <label className="loginAck">
              <input type="checkbox" checked={ack} onChange={(event) => setAck(event.target.checked)} />
              <span>我了解這是<b>正式實單</b>環境，將以 .env 設定的帳號連線、可下真實委託。</span>
            </label>
          ) : null}
          {error ? <p className="loginError">{error}</p> : null}
        </div>

        <button type="button" className="loginSubmit" disabled={busy || (isLive && !ack)} onClick={() => void submit()}>
          {busy ? <><Loader2 size={15} className="spin" /> 連線中…</> : `登入${isLive ? "（實單）" : "（模擬）"}`}
        </button>
      </div>
    </div>
  );
}
