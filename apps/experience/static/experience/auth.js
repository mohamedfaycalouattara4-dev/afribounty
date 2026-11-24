(() => {
  const decode = (value) => Uint8Array.from(atob(value.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - value.length % 4) % 4)), (character) => character.charCodeAt(0));
  const encode = (value) => {
    const bytes = new Uint8Array(value);
    let binary = "";
    bytes.forEach((byte) => { binary += String.fromCharCode(byte); });
    return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  };

  const register = async (options, csrf) => {
    const publicKey = {
      ...options,
      challenge: decode(options.challenge),
      user: { ...options.user, id: decode(options.user.id) },
      excludeCredentials: (options.excludeCredentials || []).map((item) => ({ ...item, id: decode(item.id) })),
    };
    const credential = await navigator.credentials.create({ publicKey });
    return {
      id: credential.id,
      rawId: encode(credential.rawId),
      type: credential.type,
      response: {
        clientDataJSON: encode(credential.response.clientDataJSON),
        attestationObject: encode(credential.response.attestationObject),
      },
      csrf,
    };
  };

  const authenticate = async (options, csrf) => {
    const publicKey = {
      ...options,
      challenge: decode(options.challenge),
      allowCredentials: (options.allowCredentials || []).map((item) => ({ ...item, id: decode(item.id) })),
    };
    const credential = await navigator.credentials.get({ publicKey });
    return {
      id: credential.id,
      rawId: encode(credential.rawId),
      type: credential.type,
      response: {
        clientDataJSON: encode(credential.response.clientDataJSON),
        authenticatorData: encode(credential.response.authenticatorData),
        signature: encode(credential.response.signature),
        userHandle: credential.response.userHandle ? encode(credential.response.userHandle) : null,
      },
      csrf,
    };
  };

  const run = async () => {
    const button = document.querySelector("[data-auth-action]");
    if (!button) return;
    const status = document.getElementById("auth-status");
    const csrf = document.querySelector("[name=csrfmiddlewaretoken]")?.value;
    const optionsNode = document.getElementById("auth-options");
    if (!optionsNode) return;
    const options = JSON.parse(optionsNode.textContent);
    button.addEventListener("click", async () => {
      button.disabled = true;
      status.textContent = button.dataset.authAction === "register"
        ? "Confirmez maintenant votre identité sur votre appareil. Aucune donnée biométrique ne quitte votre appareil."
        : "Confirmez votre identité sur votre appareil. Si vous n’avez pas lancé cette demande, annulez-la.";
      try {
        if (!window.PublicKeyCredential || !navigator.credentials) throw new Error("Votre navigateur ne prend pas en charge les passkeys.");
        const payload = button.dataset.authAction === "register" ? await register(options, csrf) : await authenticate(options, csrf);
        const response = await fetch(window.location.pathname, {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
          body: JSON.stringify(payload),
          credentials: "same-origin",
        });
        if (!response.ok) throw new Error("La vérification de sécurité a échoué. Aucun changement n’a été enregistré.");
        if (button.dataset.authAction === "register") {
          document.open();
          document.write(await response.text());
          document.close();
        } else {
          window.location.href = response.url;
        }
      } catch (error) {
        status.textContent = error.message || "Opération annulée. Aucun changement n’a été enregistré.";
        button.disabled = false;
      }
    });
  };

  window.addEventListener("DOMContentLoaded", run);
})();
