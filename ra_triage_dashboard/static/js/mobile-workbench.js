/* Phone-only presentation. Move original controls so IDs, permissions and handlers survive. */
function bindMobileWorkbench() {
  const menu = document.getElementById("mobileTopbarMore");
  if (!menu || menu.dataset.bound === "1") return;
  menu.dataset.bound = "1";
  const panel = document.getElementById("mobileTopbarPanel");
  const media = window.matchMedia("(max-width: 639px)");
  const narrow = window.matchMedia("(max-width: 439px)");
  const slots = ["themeToggleButton", "languageToggleButton", "shortcutHelpButton", "gtSyncControl", "refreshButton"].map((id) => {
    const node = document.getElementById(id);
    if (!node) return null;
    const marker = document.createComment(`mobile-slot:${id}`);
    node.before(marker);
    return { node, marker, narrowOnly: id === "refreshButton" };
  }).filter(Boolean);
  const sync = () => {
    menu.open = false;
    slots.forEach(({node, marker, narrowOnly}) => {
      if (narrowOnly ? narrow.matches : media.matches) panel.appendChild(node);
      else marker.after(node);
    });
  };
  media.addEventListener("change", sync);
  narrow.addEventListener("change", sync);
  sync();
  document.addEventListener("click", (event) => {
    if (!menu.contains(event.target)) menu.open = false;
    const jump = event.target.closest("[data-mobile-scroll-target]");
    if (jump) {
      const target = document.getElementById(jump.dataset.mobileScrollTarget);
      target?.scrollIntoView({block: "start", behavior: "auto"});
      if (target && media.matches) {
        const headerHeight = document.querySelector(".topbar")?.getBoundingClientRect().height || 0;
        window.scrollBy({top: -headerHeight, behavior: "auto"});
      }
      if (target) { target.setAttribute("tabindex", "-1"); target.focus({preventScroll: true}); }
    }
    const disclosure = event.target.closest("[data-mobile-disclosure]");
    if (disclosure) {
      const target = document.getElementById(disclosure.dataset.mobileDisclosure);
      if (!target) return;
      const open = target.classList.toggle("mobile-expanded");
      disclosure.setAttribute("aria-expanded", String(open));
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && menu.open) {
      menu.open = false;
      menu.querySelector("summary").focus();
    }
  });
}
