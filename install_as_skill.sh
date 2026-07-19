#!/bin/bash

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_info()    { echo -e "${BLUE}(i)  $1${NC}"; }
print_success() { echo -e "${GREEN}[OK] $1${NC}"; }
print_warning() { echo -e "${YELLOW}(!)  $1${NC}"; }
print_error()   { echo -e "${RED}[X] $1${NC}"; }
print_header()  { echo ""; echo "========================================"; echo "$1"; echo "========================================"; echo ""; }

TARGET="auto"

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --target)
                TARGET="${2:-}"
                shift 2
                ;;
            --target=*)
                TARGET="${1#*=}"
                shift
                ;;
            *)
                print_error "未知参数: $1"
                echo "用法: bash install_as_skill.sh [--target auto|claude|codex|openclaw]"
                exit 1
                ;;
        esac
    done
}

resolve_install_target() {
    case "$TARGET" in
        auto)
            if [ -n "${CODEX_HOME:-}" ]; then
                echo "codex"
            elif [ -d "$HOME/.codex" ]; then
                echo "codex"
            elif [ -d "$HOME/.claude" ]; then
                echo "claude"
            else
                echo "codex"
            fi
            ;;
        claude|codex|openclaw)
            echo "$TARGET"
            ;;
        *)
            print_error "不支持的 target: $TARGET"
            echo "可选值: auto | claude | codex | openclaw"
            exit 1
            ;;
    esac
}

resolve_skill_dir() {
    case "$1" in
        claude)
            echo "$HOME/.claude/skills/nihaisha"
            ;;
        codex)
            echo "${CODEX_HOME:-$HOME/.codex}/skills/nihaisha"
            ;;
        openclaw)
            echo "$HOME/skills/nihaisha"
            ;;
    esac
}

resolve_agent_label() {
    case "$1" in
        claude)
            echo "Claude Code"
            ;;
        codex)
            echo "Codex"
            ;;
        openclaw)
            echo "OpenClaw"
            ;;
    esac
}

main() {
    parse_args "$@"

    print_header "nihaisha -- 安装"

    INSTALL_TARGET="$(resolve_install_target)"
    SKILL_DIR="$(resolve_skill_dir "$INSTALL_TARGET")"
    AGENT_LABEL="$(resolve_agent_label "$INSTALL_TARGET")"

    print_info "目标 agent: $AGENT_LABEL"
    print_info "目标目录: $SKILL_DIR"
    print_info "安装模式: 轻量 Skill（不复制本地 RAG 资产）"

    if [ -d "$SKILL_DIR" ]; then
        print_warning "Skill 目录已存在: $SKILL_DIR"
        read -p "是否覆盖？(y/N) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            print_info "取消"
            exit 0
        fi
        rm -rf "$SKILL_DIR"
    fi

    print_info "创建 Skill 目录..."
    mkdir -p "$SKILL_DIR"

    print_info "复制 skill 文件..."
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    rsync -a \
        --exclude='.git' \
        --exclude='.gitignore' \
        --exclude='README.md' \
        --exclude='install_as_skill.sh' \
        --exclude='__pycache__' \
        --exclude='.pytest_cache' \
        --exclude='.ruff_cache' \
        --exclude='.venv' \
        --exclude='.coverage' \
        --exclude='.env' \
        --exclude='*.egg-info' \
        --exclude='LOCAL_USABILITY_REPORT.md' \
        --exclude='data' \
        --exclude='output' \
        --exclude='tests' \
        --exclude='evals' \
        --exclude='docs/local' \
        --exclude='docs/superpowers' \
        "$SCRIPT_DIR/" "$SKILL_DIR/"

    print_header "安装完成"
    print_success "已装到 $SKILL_DIR"
    print_info "重启 $AGENT_LABEL 让 skill 生效"
}

trap 'print_error "安装过程出错"; exit 1' ERR

main "$@"
