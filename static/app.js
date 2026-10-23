document.addEventListener("DOMContentLoaded", () => {
  const settings = document.querySelectorAll("[data-setting]");
  settings.forEach((toggle) => {
    const key = `pygold:${toggle.dataset.setting}`;
    const saved = localStorage.getItem(key);
    if (saved !== null) toggle.checked = saved === "true";
    toggle.addEventListener("change", () => {
      localStorage.setItem(key, String(toggle.checked));
      if (toggle.dataset.setting === "dark-theme") {
        document.body.classList.toggle("light-theme", !toggle.checked);
      }
    });
  });
  const theme = localStorage.getItem("pygold:dark-theme");
  if (theme === "false") document.body.classList.add("light-theme");

  const chatMessages = document.getElementById("chat-messages");
  if (chatMessages) {
    let lastMessageId = Number(chatMessages.dataset.lastId || 0);
    const pollMessages = async () => {
      try {
        const response = await fetch(
          `${chatMessages.dataset.pollUrl}?after=${lastMessageId}`,
          { headers: { Accept: "application/json" } },
        );
        if (!response.ok) return;
        const messages = await response.json();
        messages.forEach((message) => {
          const article = document.createElement("article");
          article.className = message.sender === document.querySelector(".sidebar-user strong")?.textContent
            ? "chat-message own-message"
            : "chat-message";
          article.dataset.messageId = String(message.id);
          const author = document.createElement("strong");
          author.textContent = message.sender;
          const body = document.createElement("p");
          body.textContent = message.body;
          const time = document.createElement("time");
          time.textContent = new Date(message.created_at).toLocaleTimeString([], {
            hour: "2-digit",
            minute: "2-digit",
          });
          article.append(author, body, time);
          chatMessages.append(article);
          lastMessageId = Math.max(lastMessageId, message.id);
        });
        if (messages.length) chatMessages.scrollTop = chatMessages.scrollHeight;
      } catch (error) {
        console.error("No se pudieron actualizar los mensajes.", error);
      }
    };
    chatMessages.scrollTop = chatMessages.scrollHeight;
    window.setInterval(pollMessages, 5000);
  }

  const fileInput = document.getElementById("game-zip");
  const fileName = document.getElementById("file-name");
  if (fileInput && fileName) {
    fileInput.addEventListener("change", () => {
      fileName.textContent = fileInput.files.length ? fileInput.files[0].name : "Arrastra tu ZIP aquí o selecciónalo";
    });
  }

  const profileForm = document.getElementById("profile-form");
  if (profileForm) {
    const nameDisplay = document.getElementById("profile-name-display");
    const bioDisplay = document.getElementById("profile-bio-display");
    const avatar = document.getElementById("profile-avatar");
    const saved = JSON.parse(localStorage.getItem("pygold:profile") || "{}");
    const updateProfile = (profile) => {
      nameDisplay.textContent = profile.nickname || "Jugador";
      bioDisplay.textContent = profile.bio || "Añade una bio para contarle al mundo quién eres.";
      avatar.textContent = (profile.nickname || "P").slice(0, 1).toUpperCase();
    };
    updateProfile(saved);
    profileForm.elements.nickname.value = saved.nickname || "";
    profileForm.elements.bio.value = saved.bio || "";
    document.getElementById("edit-profile-button").addEventListener("click", () => {
      profileForm.classList.toggle("hidden");
    });
    profileForm.addEventListener("submit", (event) => {
      event.preventDefault();
      const profile = {
        nickname: profileForm.elements.nickname.value.trim(),
        bio: profileForm.elements.bio.value.trim(),
      };
      localStorage.setItem("pygold:profile", JSON.stringify(profile));
      updateProfile(profile);
      profileForm.classList.add("hidden");
    });
  }

  const dialog = document.getElementById("chat-dialog");
  if (dialog) {
    ["new-chat-button", "start-chat-button", "create-group-button"].forEach((id) => {
      document.getElementById(id).addEventListener("click", () => dialog.showModal());
    });
    document.getElementById("save-group").addEventListener("click", (event) => {
      if (!document.getElementById("group-name").value.trim()) {
        event.preventDefault();
        document.getElementById("group-name").focus();
      }
    });
  }

  const canvas = document.getElementById("design-canvas");
  if (!canvas) return;
  const context = canvas.getContext("2d");
  const colorInput = document.getElementById("paint-color");
  const sizeInput = document.getElementById("brush-size");
  const toolButtons = document.querySelectorAll("[data-tool]");
  const undoStack = [];
  let activeTool = "brush";
  let drawing = false;
  let start = null;
  let snapshot = null;

  context.fillStyle = "#fff";
  context.fillRect(0, 0, canvas.width, canvas.height);
  const saveSnapshot = () => {
    undoStack.push(context.getImageData(0, 0, canvas.width, canvas.height));
    if (undoStack.length > 25) undoStack.shift();
  };
  const point = (event) => {
    const bounds = canvas.getBoundingClientRect();
    return {
      x: (event.clientX - bounds.left) * canvas.width / bounds.width,
      y: (event.clientY - bounds.top) * canvas.height / bounds.height,
    };
  };
  const strokeStyle = () => {
    context.strokeStyle = activeTool === "eraser" ? "#ffffff" : colorInput.value;
    context.lineWidth = Number(sizeInput.value);
    context.lineCap = "round";
    context.lineJoin = "round";
  };
  const drawShape = (from, to) => {
    context.beginPath();
    if (activeTool === "line") {
      context.moveTo(from.x, from.y);
      context.lineTo(to.x, to.y);
    } else if (activeTool === "rectangle") {
      context.rect(from.x, from.y, to.x - from.x, to.y - from.y);
    } else {
      const radiusX = (to.x - from.x) / 2;
      const radiusY = (to.y - from.y) / 2;
      context.ellipse(from.x + radiusX, from.y + radiusY, Math.abs(radiusX), Math.abs(radiusY), 0, 0, Math.PI * 2);
    }
    context.stroke();
  };

  toolButtons.forEach((button) => button.addEventListener("click", () => {
    activeTool = button.dataset.tool;
    toolButtons.forEach((item) => item.classList.toggle("selected", item === button));
  }));
  canvas.addEventListener("pointerdown", (event) => {
    drawing = true;
    canvas.setPointerCapture(event.pointerId);
    start = point(event);
    saveSnapshot();
    snapshot = context.getImageData(0, 0, canvas.width, canvas.height);
    if (activeTool === "brush" || activeTool === "eraser") {
      strokeStyle();
      context.beginPath();
      context.moveTo(start.x, start.y);
    }
  });
  canvas.addEventListener("pointermove", (event) => {
    if (!drawing) return;
    const current = point(event);
    if (activeTool === "brush" || activeTool === "eraser") {
      strokeStyle();
      context.lineTo(current.x, current.y);
      context.stroke();
    } else {
      context.putImageData(snapshot, 0, 0);
      strokeStyle();
      drawShape(start, current);
    }
  });
  const finishDrawing = () => { drawing = false; };
  canvas.addEventListener("pointerup", finishDrawing);
  canvas.addEventListener("pointercancel", finishDrawing);
  document.getElementById("undo-button").addEventListener("click", () => {
    const previous = undoStack.pop();
    if (previous) context.putImageData(previous, 0, 0);
  });
  document.getElementById("clear-button").addEventListener("click", () => {
    saveSnapshot();
    context.fillStyle = "#fff";
    context.fillRect(0, 0, canvas.width, canvas.height);
  });
  document.getElementById("download-button").addEventListener("click", () => {
    const link = document.createElement("a");
    link.download = `${document.getElementById("garment").value.toLowerCase()}.png`;
    link.href = canvas.toDataURL("image/png");
    link.click();
  });
});
