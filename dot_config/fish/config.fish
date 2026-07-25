# Fish Shell Configuration
# ~/.config/fish/config.fish

# ============================================================================
# PATH
# ============================================================================

fish_add_path /opt/homebrew/bin
fish_add_path ~/.local/bin
fish_add_path ~/.config/emacs/bin
fish_add_path ~/.cargo/bin
fish_add_path ~/go/bin

# ============================================================================
# VI MODE & KEY BINDINGS
# ============================================================================

# Enable vi key bindings
fish_vi_key_bindings

# Custom key bindings
function fish_user_key_bindings
    for mode in insert default visual
        bind -M $mode \cf forward-char
        bind -M $mode \ef forward-word
    end
end

# Cursor shape configuration
set fish_vi_force_cursor 1
set fish_cursor_default block
set fish_cursor_insert line
set fish_cursor_replace_one underscore
set fish_cursor_replace underscore
set fish_cursor_external line
set fish_cursor_visual block

# ============================================================================
# THEME
# ============================================================================

# Pure prompt colors (if using pure theme)
set --universal pure_color_primary 18CAE6
set --universal pure_color_success A220EA

# Theme date format
set -g theme_date_format "+ %H:%M"

# ============================================================================
# ALIASES
# ============================================================================

# Git shortcuts
alias ga="git add ."
alias gc="git commit"
alias gpu="git push"
alias gpl="git pull"
alias gs="git status"
alias gd="git diff"
alias gl="git log --oneline --graph --decorate"

# Utilities
alias mvall="find . -mindepth 2 -type f -exec mv -i '{}' . ';'"
# Modern replacements
alias y="yazi"

# List variations
alias ll="ls -l"
alias la="ls -lah"

# Modern CLI tools (if installed)
if command -v eza > /dev/null
    alias ls="eza --icons"
    alias ll="eza --icons -l"
    alias la="eza --icons -la"
end

if command -v bat > /dev/null
    alias cat="bat"
end

if command -v btm > /dev/null
    alias top="btm"
end

# Safety nets
alias rm="rm -i"
alias mv="mv -i"
alias cp="cp -i"

# Chezmoi shortcuts
alias cz="chezmoi"
alias cup="chezmoi-sync"          # Pull, classify drift, and safely converge
alias czd="chezmoi diff"          # See what would change
alias cze="chezmoi edit"          # Edit a managed file
alias czs="chezmoi status"        # Check status

# Claude shortcuts
alias c="claude"
alias cdang="claude --permission-mode bypassPermissions"
alias ccr="claude --resume --model opusplan --effort auto"

# ============================================================================
# FUNCTIONS
# ============================================================================

# Quick directory creation and navigation
function mkcd
    mkdir -p $argv[1]
    cd $argv[1]
end

# Extract various archive types
function extract
    if test -f $argv[1]
        switch $argv[1]
            case '*.tar.bz2'
                tar xjf $argv[1]
            case '*.tar.gz'
                tar xzf $argv[1]
            case '*.bz2'
                bunzip2 $argv[1]
            case '*.gz'
                gunzip $argv[1]
            case '*.tar'
                tar xf $argv[1]
            case '*.tbz2'
                tar xjf $argv[1]
            case '*.tgz'
                tar xzf $argv[1]
            case '*.zip'
                unzip $argv[1]
            case '*.Z'
                uncompress $argv[1]
            case '*.7z'
                7z x $argv[1]
            case '*'
                echo "'$argv[1]' cannot be extracted"
        end
    else
        echo "'$argv[1]' is not a valid file"
    end
end

# Quick find
function f
    find . -name "*$argv[1]*"
end

# ============================================================================
# TOOL INITIALIZATION
# ============================================================================

# Starship prompt
if command -v starship > /dev/null
    starship init fish | source
end

# Zoxide (smart cd)
if command -v zoxide > /dev/null
    zoxide init fish | source
end

# Atuin (shell history)
if command -v atuin > /dev/null
    atuin init fish | source
end

# ============================================================================
# ENVIRONMENT-SPECIFIC SETTINGS
# ============================================================================

# Load local customizations if they exist
if test -f ~/.config/fish/config.local.fish
    source ~/.config/fish/config.local.fish
end

set -gx LANG en_US.UTF-8
set -gx LC_ALL en_US.UTF-8
set -gx EDITOR nvim
set -gx VISUAL nvim
