(() => {
  const actions = document.querySelector(".top-actions");
  if (!actions) return;

  const navigation = [
    ["/stock/", "看股票"],
    ["/ranking/", "排行榜"],
    ["/screener/", "找股票"],
    ["/watchlist/", "我的追蹤"],
    ["/research/", "研究與資料"],
  ];
  const currentPath = window.location.pathname;
  const fragment = document.createDocumentFragment();
  for (const [href, label] of navigation) {
    const link = document.createElement("a");
    link.href = href;
    link.className = "text-link nav-link";
    link.textContent = label;
    if (currentPath === href) {
      link.classList.add("active");
      link.setAttribute("aria-current", "page");
    }
    fragment.appendChild(link);
  }
  actions.replaceChildren(fragment);
})();
