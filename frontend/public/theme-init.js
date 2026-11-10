// Sets the colour theme before the first paint, so that a dark-mode visitor never sees a light
// flash (or the reverse). It is a separate same-origin file, loaded synchronously from <head>,
// because the Content-Security-Policy forbids inline scripts.
//
// The stored preference is "light" or "dark"; anything else means "follow the operating system".
(function () {
  var theme = null;
  try {
    theme = window.localStorage.getItem("sourcewise-theme");
  } catch (error) {
    // Storage can be unavailable (private mode, blocked cookies); fall through to the OS setting.
  }
  if (theme !== "light" && theme !== "dark") {
    theme = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  document.documentElement.setAttribute("data-theme", theme);
})();
