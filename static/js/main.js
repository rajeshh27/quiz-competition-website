/* main.js — Global utilities */

// Flash auto-dismiss
document.querySelectorAll('.flash-msg').forEach(msg => {
  setTimeout(() => {
    msg.style.transition = 'opacity .4s, transform .4s';
    msg.style.opacity = '0';
    msg.style.transform = 'translateX(120%)';
    setTimeout(() => msg.remove(), 400);
  }, 4000);
});

// Sidebar toggle for mobile
window.toggleSidebar = function () {
  const sb = document.getElementById('sidebar');
  if (sb) sb.classList.toggle('open');
};

// Smooth body fade-in
document.addEventListener('DOMContentLoaded', () => {
  document.body.style.opacity = '0';
  document.body.style.transition = 'opacity .35s ease';
  requestAnimationFrame(() => requestAnimationFrame(() => {
    document.body.style.opacity = '1';
  }));
});
