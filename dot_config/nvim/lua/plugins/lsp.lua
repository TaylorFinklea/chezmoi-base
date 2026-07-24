return {
  -- LSP Configuration
  {
    "neovim/nvim-lspconfig",
    opts = function(_, opts)
      opts.diagnostics = opts.diagnostics or {}

      local virtual_text = opts.diagnostics.virtual_text
      opts.diagnostics.virtual_text = function(_, bufnr)
        local filetype = vim.bo[bufnr].filetype
        if filetype == "markdown" or filetype == "markdown.mdx" then
          return false
        end
        return virtual_text
      end

      opts.servers = vim.tbl_deep_extend("force", opts.servers or {}, {
        -- Python
        pyright = {},

        -- Rust
        rust_analyzer = {
          settings = {
            ["rust-analyzer"] = {
              cargo = {
                allFeatures = true,
              },
              checkOnSave = {
                command = "clippy",
              },
            },
          },
        },

        -- TypeScript/JavaScript
        ts_ls = {},
      })
    end,
  },
}
