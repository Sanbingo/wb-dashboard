/**
 * WB 多店铺切换器
 * - 统一给所有 /api/* 请求附加 store 参数
 * - 支持 fetch / XMLHttpRequest
 * - 选择结果存 localStorage，页面刷新生效
 */
(function () {
  var KEY = 'wb_store';
  var DEFAULT = 'wb1';
  var params = new URLSearchParams(location.search);
  var store = params.get('store') || localStorage.getItem(KEY) || DEFAULT;
  localStorage.setItem(KEY, store);
  window.WB_STORE = store;

  function addStore(url) {
    if (typeof url !== 'string') return url;
    if (url.indexOf('/api/') !== 0) return url;
    if (/[?&]store=/.test(url)) return url;
    return url + (url.indexOf('?') >= 0 ? '&' : '?') + 'store=' + encodeURIComponent(store);
  }

  var rawFetch = window.fetch;
  window.fetch = function (input, init) {
    if (typeof input === 'string') {
      input = addStore(input);
    } else if (input && typeof input === 'object' && input.url) {
      var u = addStore(input.url);
      if (u !== input.url) input = new Request(u, input);
    }
    return rawFetch.call(this, input, init);
  };

  var rawOpen = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function (method, url) {
    var args = Array.prototype.slice.call(arguments);
    args[1] = addStore(url);
    return rawOpen.apply(this, args);
  };

  var css = ''
    + '.wb-store-switch{display:inline-flex;align-items:center;gap:6px;margin-left:auto;flex-shrink:0}'
    + '.wb-store-switch .wb-store-label{font-size:12px;color:#8c8c8c}'
    + '.wb-store-switch select{height:32px;padding:0 28px 0 10px;border:1px solid #d9d9d9;border-radius:6px;background:#fff;color:#262626;font-size:13px;cursor:pointer;outline:none}'
    + '.wb-store-switch select:focus{border-color:#1677ff;box-shadow:0 0 0 2px rgba(22,119,255,.12)}'
    + '.wb-store-switch .wb-summary-link{font-size:12px;color:#1677ff;text-decoration:none;padding:5px 10px;border:1px solid #91caff;border-radius:6px;background:#e6f4ff;white-space:nowrap}'
    + '.wb-store-switch .wb-summary-link:hover{background:#bae0ff}';

  function injectCss() {
    var s = document.createElement('style');
    s.textContent = css;
    document.head.appendChild(s);
  }

  function buildSwitch(stores) {
    var box = document.createElement('div');
    box.className = 'wb-store-switch';
    var label = document.createElement('span');
    label.className = 'wb-store-label';
    label.textContent = '店铺';
    var sel = document.createElement('select');
    stores.forEach(function (s) {
      var o = document.createElement('option');
      o.value = s.key;
      o.textContent = s.name + (s.seller ? ' · ' + s.seller : '');
      if (s.key === store) o.selected = true;
      sel.appendChild(o);
    });
    sel.addEventListener('change', function () {
      localStorage.setItem(KEY, sel.value);
      var u = new URL(location.href);
      u.searchParams.set('store', sel.value);
      location.href = u.toString();
    });
    box.appendChild(label);
    box.appendChild(sel);

    if (location.pathname.indexOf('wb-summary') < 0) {
      var a = document.createElement('a');
      a.href = 'wb-summary.html';
      a.className = 'wb-summary-link';
      a.textContent = '📊 汇总报表';
      box.appendChild(a);
    }
    return box;
  }

  document.addEventListener('DOMContentLoaded', function () {
    if (location.pathname.indexOf('wb-summary') >= 0) return;
    injectCss();
    fetch('/api/stores').then(function (r) { return r.json(); }).then(function (d) {
      var stores = (d && d.stores) || [];
      if (stores.length < 2) return;
      var box = buildSwitch(stores);
      var host = document.querySelector('.header') || document.querySelector('.header-actions');
      if (host) {
        host.appendChild(box);
      } else {
        box.style.position = 'fixed';
        box.style.top = '12px';
        box.style.right = '12px';
        box.style.zIndex = '9999';
        box.style.background = '#fff';
        box.style.padding = '6px 10px';
        box.style.borderRadius = '8px';
        box.style.boxShadow = '0 2px 8px rgba(0,0,0,.12)';
        document.body.appendChild(box);
      }
    }).catch(function () {});
  });
})();
