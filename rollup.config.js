import commonjs from "@rollup/plugin-commonjs";
import json from "@rollup/plugin-json";
import { nodeResolve } from "@rollup/plugin-node-resolve";
import replace from "@rollup/plugin-replace";
import typescript from "@rollup/plugin-typescript";

export default {
  input: "./src/index.tsx",
  output: {
    file: "dist/index.js",
    format: "iife",
    globals: {
      react: "SP_REACT",
      "react-dom": "SP_REACTDOM",
      "@decky/ui": "DFL",
      "@decky/api": "DECKY_API",
    },
    exports: "default",
  },
  external: ["react", "react-dom", "@decky/ui", "@decky/api"],
  plugins: [
    commonjs(),
    nodeResolve(),
    typescript(),
    json(),
    replace({
      preventAssignment: true,
      "process.env.NODE_ENV": JSON.stringify("production"),
    }),
  ],
};
