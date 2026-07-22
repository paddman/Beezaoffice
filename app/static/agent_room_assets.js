(() => {
  document.addEventListener(
    "error",
    (event) => {
      const image = event.target;
      if (!(image instanceof HTMLImageElement)) return;
      if (image.dataset.agentRoomFallbackApplied === "true") return;
      if (image.classList.contains("agent-room-foreground")) {
        image.remove();
        return;
      }
      if (!image.classList.contains("agent-room-avatar") && !image.classList.contains("agent-room-card-avatar")) {
        return;
      }
      image.dataset.agentRoomFallbackApplied = "true";
      image.src = "/static/assets/agent-avatar-placeholder.svg";
    },
    true,
  );
})();
