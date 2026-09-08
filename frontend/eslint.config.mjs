import nextCoreWebVitals from "eslint-config-next/core-web-vitals";
import nextTypeScript from "eslint-config-next/typescript";

// eslint-config-next 16 ships native flat config, so the previous
// FlatCompat shim is gone — wrapping it now throws "Converting circular
// structure to JSON". Spread the exported arrays directly instead.
//
// `next lint` was removed in Next 16 and `next build` no longer lints, so
// this config is the ONLY thing enforcing the rules the production build
// used to catch. Run `npm run lint` alongside `npm run build`.
const eslintConfig = [
  {
    ignores: [
      ".next/**",
      "out/**",
      "build/**",
      "next-env.d.ts",
      "coverage/**",
    ],
  },
  ...nextCoreWebVitals,
  ...nextTypeScript,
];

export default eslintConfig;
