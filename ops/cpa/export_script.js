(async () => {
    console.log("正在读取当前 ChatGPT session...");
    const session = await fetch("/api/auth/session").then(r => r.json());
    if (!session?.accessToken) {
        console.error("未检测到 accessToken，请先登录 chatgpt.com 并切到目标 workspace。");
        return;
    }

    function base64UrlDecode(value) {
        const normalized = value.replace(/-/g, "+").replace(/_/g, "/");
        const padded = normalized + "=".repeat((4 - normalized.length % 4) % 4);
        const binary = atob(padded);
        const bytes = new Uint8Array(binary.length);
        for (let i = 0; i < binary.length; i++) {
            bytes[i] = binary.charCodeAt(i);
        }
        return new TextDecoder().decode(bytes);
    }

    function parseJwtPayload(token) {
        const parts = String(token || "").split(".");
        if (parts.length < 2) return null;
        try {
            return JSON.parse(base64UrlDecode(parts[1]));
        } catch (err) {
            return null;
        }
    }

    function sanitizeFilePart(value) {
        return String(value || "unknown")
            .trim()
            .replace(new RegExp("[^a-zA-Z0-9._-]+", "g"), "_")
            .replace(new RegExp("_+", "g"), "_")
            .replace(new RegExp("^_+|_+$", "g"), "");
    }

    function downloadJson(fileName, data) {
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = fileName;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }

    const payload = parseJwtPayload(session.accessToken);
    const auth = payload?.["https://api.openai.com/auth"] || {};
    const accountId = (auth.chatgpt_account_id || session.account?.id || "").trim().toLowerCase();
    const sessionAccountId = (session.account?.id || "").trim().toLowerCase();
    const planType = auth.chatgpt_plan_type || session.account?.planType || "unknown";
    const expiresAt = payload?.exp ? new Date(payload.exp * 1000).toISOString() : session.expires;
    const email = session.user?.email || "unknown@domain.com";
    const name = session.account?.name || session.user?.name || "ChatGPT Account";

    if (!accountId) {
        console.error("无法从当前 session 解析 account_id。");
        return;
    }
    if (sessionAccountId && accountId !== sessionAccountId) {
        console.error("当前 session account 与 accessToken claim 不一致，停止导出。", {
            session_account_id: sessionAccountId,
            token_account_id: accountId
        });
        return;
    }

    const cpaAccount = {
        type: "codex",
        email,
        password: "",
        expired: expiresAt,
        id_token: session.accessToken,
        account_id: accountId,
        workspace_id: accountId,
        chatgpt_account_id: accountId,
        disabled: false,
        access_token: session.accessToken,
        session_token: session.sessionToken || "",
        last_refresh: new Date().toISOString(),
        refresh_token: "",
        name,
        plan_type: planType,
        chatgpt_plan_type: planType,
        source: "chatgpt_web_session"
    };

    const safeEmail = email.replace(new RegExp("[@.]", "g"), "_");
    const fileName = "codex-" + safeEmail + "_" + sanitizeFilePart(name) + "_" + accountId.slice(0, 8) + ".json";
    downloadJson(fileName, cpaAccount);

    console.log("已导出当前 CPA 凭证:", fileName);
    console.log({
        account_id: accountId,
        plan_type: planType,
        expires: expiresAt
    });
})();
