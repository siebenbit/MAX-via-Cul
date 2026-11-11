export const cardStyles = `
:host{display:block;color:var(--primary-text-color,#222);font-family:var(--paper-font-body1_-_font-family,inherit)}
*{box-sizing:border-box}
ha-card{display:block;background:var(--ha-card-background,var(--card-background-color,#fff));border:1px solid var(--divider-color,#ddd);border-radius:var(--ha-card-border-radius,12px);padding:16px}
h2,.title{font-size:1.15rem;font-weight:600;margin:0;line-height:1.3;overflow-wrap:anywhere}
h3{font-size:1rem;margin:0 0 12px}
.header{display:flex;justify-content:space-between;align-items:center;gap:12px}
button,input,select,a.button-link{font:inherit;color:inherit;background:var(--ha-card-background,var(--card-background-color,#fff));border:1px solid var(--divider-color,#ccc);border-radius:10px;min-height:44px;padding:8px 12px;max-width:100%;min-width:0}
input[type=checkbox]{width:20px;height:20px;min-height:0;padding:0;vertical-align:middle;accent-color:var(--primary-color,#519eb5)}
a.button-link{display:inline-flex;align-items:center;justify-content:center;text-decoration:none;white-space:nowrap}
button{cursor:pointer}button:hover:not(:disabled),a.button-link:hover{background:var(--secondary-background-color,#eee)}
button:disabled,input:disabled,select:disabled{opacity:.5;cursor:default}
button:focus-visible,input:focus-visible,select:focus-visible,summary:focus-visible,a.button-link:focus-visible{outline:2px solid var(--primary-color,#519eb5);outline-offset:2px}
button.primary,button.selected{background:var(--primary-text-color,#222);color:var(--card-background-color,#fff)}
.badge{background:var(--secondary-background-color,#eee);border-radius:8px;padding:4px 8px;font-size:.8rem}
.notice{background:var(--secondary-background-color,#eee);border-radius:8px;padding:10px;margin:12px 0;overflow-wrap:anywhere}
.error{color:var(--error-color,#b3261e);overflow-wrap:anywhere}
.muted,small,.subtitle{color:var(--secondary-text-color,#666);font-size:.85rem;line-height:1.5}
section{border-top:1px solid var(--divider-color,#ddd);margin-top:16px;padding-top:16px}
summary{cursor:pointer;min-height:32px}details{margin-top:12px}
.actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:16px}
@media(max-width:480px){ha-card{padding:12px}}
`;

// Shared modal layout: fixed header/actions, independently scrolling form body.
export const dialogStyles = `
dialog{position:fixed;inset:auto 0;top:calc(var(--dialog-viewport-top,0px) + var(--dialog-viewport-height,100dvh)/2);transform:translateY(-50%);margin:0 auto;width:min(28rem,calc(100vw - 32px));max-width:none;max-height:calc(var(--dialog-viewport-height,100dvh) - 32px);padding:0;border:1px solid var(--divider-color,#ddd);border-radius:var(--ha-card-border-radius,12px);background:var(--ha-card-background,var(--card-background-color,#fff));color:var(--primary-text-color,#222);box-shadow:0 16px 48px #0005}
dialog::backdrop{background:#0008}
dialog form{display:flex;flex-direction:column;max-height:calc(var(--dialog-viewport-height,100dvh) - 34px);margin:0}
dialog header{padding:20px 24px 16px;flex-shrink:0;border-bottom:1px solid var(--divider-color,#ddd)}
dialog header p{margin:6px 0 0}
.dialog-body{padding:20px 24px;display:grid;grid-template-columns:minmax(0,1fr);gap:8px;overflow:auto;min-height:0;overscroll-behavior:contain}
.dialog-body label{font-weight:600;font-size:.9rem}.dialog-body label:not(:first-child){margin-top:12px}
.dialog-body input,.dialog-body select{width:100%;font-size:16px}
.dialog-body .error{margin:8px 0 0}
dialog footer{display:flex;gap:12px;justify-content:flex-end;padding:16px 24px;border-top:1px solid var(--divider-color,#ddd);flex-shrink:0}
dialog footer button{flex:1;min-width:0}
@media(max-width:480px){dialog header,dialog footer{padding:16px}.dialog-body{padding:16px}}
`;
