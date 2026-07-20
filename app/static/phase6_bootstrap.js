(() => {
  if (localStorage.getItem("beezaToken")) return;
  const token = window.prompt("Enter the BeezaOffice operator token to load Governance") || "";
  if (token) localStorage.setItem("beezaToken", token);
})();
