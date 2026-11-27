export default [{
  files: ["static/**/*.js"],
  languageOptions: {
    ecmaVersion: "latest",
    sourceType: "script",
    globals: Object.fromEntries([
      "window","document","location","navigator","fetch","URL","URLSearchParams",
      "FormData","Event","CustomEvent","HTMLElement","HTMLInputElement","HTMLFormElement",
      "AbortController","AbortSignal","Option","DOMParser","File","Blob","FileReader","Image","MutationObserver","ResizeObserver",
      "IntersectionObserver","requestAnimationFrame","cancelAnimationFrame",
      "setTimeout","clearTimeout","setInterval","clearInterval","console","confirm","alert",
      "localStorage","sessionStorage","performance","CSS","history","prompt","Intl","TextDecoder"
    ].map(name => [name, "readonly"]))
  },
  rules: {
    "no-undef": "error",
    "no-unreachable": "error",
    "no-dupe-keys": "error",
    "no-duplicate-case": "error",
    "no-constant-condition": ["error", {checkLoops: "none"}],
    "no-func-assign": "error",
    "no-invalid-regexp": "error",
    "no-unsafe-finally": "error",
    "valid-typeof": "error"
  }
}];
