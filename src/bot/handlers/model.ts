import { Context, InlineKeyboard } from "grammy";
import {
  selectModel,
  fetchCurrentModel,
  getAvailableCatalogModels,
  getModelSelectionLists,
} from "../../model/manager.js";
import { formatModelForDisplay } from "../../model/types.js";
import type { CatalogModel, FavoriteModel, ModelInfo, ModelSelectionLists } from "../../model/types.js";
import { formatVariantForButton } from "../../variant/manager.js";
import { logger } from "../../utils/logger.js";
import { createMainKeyboard } from "../utils/keyboard.js";
import { getStoredAgent, resolveProjectAgent } from "../../agent/manager.js";
import { pinnedMessageManager } from "../../pinned/manager.js";
import { keyboardManager } from "../../keyboard/manager.js";
import {
  clearActiveInlineMenu,
  ensureActiveInlineMenu,
  replyWithInlineMenu,
} from "./inline-menu.js";
import { t } from "../../i18n/index.js";

function buildModelSelectionMenuText(modelLists: ModelSelectionLists): string {
  const lines = [t("model.menu.select"), t("model.menu.favorites_title")];

  if (modelLists.favorites.length === 0) {
    lines.push(t("model.menu.favorites_empty"));
  }

  lines.push(t("model.menu.recent_title"));

  if (modelLists.recent.length === 0) {
    lines.push(t("model.menu.recent_empty"));
  }

  return lines.join("\n");
}

const MODEL_PAGE_SIZE = 20;

function buildCatalogMenuText(page: number, totalPages: number): string {
  return `${t("model.menu.select")}

Showing available models from the live OpenCode provider catalog.
Page ${page + 1} / ${totalPages}`;
}

/**
 * Handle model selection callback
 * @param ctx grammY context
 * @returns true if handled, false otherwise
 */
export async function handleModelSelect(ctx: Context): Promise<boolean> {
  const callbackQuery = ctx.callbackQuery;

  if (!callbackQuery?.data || (!callbackQuery.data.startsWith("model:") && !callbackQuery.data.startsWith("modelpage:"))) {
    return false;
  }

  const isActiveMenu = await ensureActiveInlineMenu(ctx, "model");
  if (!isActiveMenu) {
    return true;
  }

  logger.debug(`[ModelHandler] Received callback: ${callbackQuery.data}`);

  try {
    if (callbackQuery.data.startsWith("modelpage:")) {
      const page = Number.parseInt(callbackQuery.data.replace("modelpage:", ""), 10);
      const currentModel = fetchCurrentModel();
      const catalog = await getAvailableCatalogModels();
      const totalPages = Math.max(1, Math.ceil(catalog.length / MODEL_PAGE_SIZE));
      const safePage = Number.isFinite(page) ? Math.min(Math.max(page, 0), totalPages - 1) : 0;
      const keyboard = await buildModelSelectionMenu(currentModel, undefined, safePage, catalog);
      const text = buildCatalogMenuText(safePage, totalPages);
      await ctx.editMessageText(text, { reply_markup: keyboard }).catch(() => {});
      await ctx.answerCallbackQuery().catch(() => {});
      return true;
    }

    if (ctx.chat) {
      keyboardManager.initialize(ctx.api, ctx.chat.id);
    }

    // Parse callback data: "model:providerID:modelID"
    const parts = callbackQuery.data.split(":");
    if (parts.length < 3) {
      logger.error(`[ModelHandler] Invalid callback data format: ${callbackQuery.data}`);
      clearActiveInlineMenu("model_select_invalid_callback");
      await ctx.answerCallbackQuery({ text: t("model.change_error_callback") }).catch(() => {});
      return true;
    }

    const providerID = parts[1];
    const modelID = parts.slice(2).join(":"); // Handle model IDs that may contain ":"

    const modelInfo: ModelInfo = {
      providerID,
      modelID,
      variant: "default", // Reset to default when switching models
    };

    // Select model and persist
    selectModel(modelInfo);

    // Update keyboard manager state (may not be initialized if no session selected)
    keyboardManager.updateModel(modelInfo);

    // Refresh context limit for new model
    await pinnedMessageManager.refreshContextLimit();

    // Update Reply Keyboard with new model and context
    const currentAgent = await resolveProjectAgent(getStoredAgent());
    const contextInfo =
      pinnedMessageManager.getContextInfo() ??
      (pinnedMessageManager.getContextLimit() > 0
        ? { tokensUsed: 0, tokensLimit: pinnedMessageManager.getContextLimit() }
        : null);

    keyboardManager.updateAgent(currentAgent);

    if (contextInfo) {
      keyboardManager.updateContext(contextInfo.tokensUsed, contextInfo.tokensLimit);
    }

    const variantName = formatVariantForButton(modelInfo.variant || "default");
    const keyboard = createMainKeyboard(
      currentAgent,
      modelInfo,
      contextInfo ?? undefined,
      variantName,
    );
    const displayName = formatModelForDisplay(modelInfo.providerID, modelInfo.modelID);

    clearActiveInlineMenu("model_selected");

    // Send confirmation message with updated keyboard
    await ctx.answerCallbackQuery({ text: t("model.changed_callback", { name: displayName }) });
    await ctx.reply(t("model.changed_message", { name: displayName }), {
      reply_markup: keyboard,
    });

    // Delete the inline menu message
    await ctx.deleteMessage().catch(() => {});

    return true;
  } catch (err) {
    clearActiveInlineMenu("model_select_error");
    logger.error("[ModelHandler] Error handling model select:", err);
    await ctx.answerCallbackQuery({ text: t("model.change_error_callback") }).catch(() => {});
    return false;
  }
}

/**
 * Build inline keyboard with favorite and recent models
 * @param currentModel Current model for highlighting
 * @returns InlineKeyboard with model selection buttons
 */
export async function buildModelSelectionMenu(
  currentModel?: ModelInfo,
  modelLists?: ModelSelectionLists,
  page = 0,
  catalogModels?: CatalogModel[],
): Promise<InlineKeyboard> {
  const keyboard = new InlineKeyboard();
  const catalog = catalogModels ?? (await getAvailableCatalogModels());

  if (catalog.length > 0) {
    const totalPages = Math.max(1, Math.ceil(catalog.length / MODEL_PAGE_SIZE));
    const safePage = Math.min(Math.max(page, 0), totalPages - 1);
    const start = safePage * MODEL_PAGE_SIZE;
    const items = catalog.slice(start, start + MODEL_PAGE_SIZE);

    items.forEach((model) => {
      const isActive =
        currentModel &&
        model.providerID === currentModel.providerID &&
        model.modelID === currentModel.modelID;

      const labelBase = model.modelName
        ? `${model.providerID}/${model.modelName}`
        : `${model.providerID}/${model.modelID}`;
      const label = isActive ? `✅ ${labelBase}` : labelBase;
      keyboard.text(label, `model:${model.providerID}:${model.modelID}`).row();
    });

    if (totalPages > 1) {
      if (safePage > 0) {
        keyboard.text("⬅️ Prev", `modelpage:${safePage - 1}`);
      }
      if (safePage < totalPages - 1) {
        keyboard.text("Next ➡️", `modelpage:${safePage + 1}`);
      }
      keyboard.row();
    }

    return keyboard;
  }

  const lists = modelLists ?? (await getModelSelectionLists());
  const favorites = lists.favorites;
  const recent = lists.recent;

  if (favorites.length === 0 && recent.length === 0) {
    logger.warn("[ModelHandler] No model choices found in favorites/recent");
    return keyboard;
  }

  const addButton = (model: FavoriteModel, prefix: string): void => {
    const isActive =
      currentModel &&
      model.providerID === currentModel.providerID &&
      model.modelID === currentModel.modelID;

    // Inline buttons use full model ID without truncation
    const label = `${prefix} ${model.providerID}/${model.modelID}`;
    const labelWithCheck = isActive ? `✅ ${label}` : label;

    keyboard.text(labelWithCheck, `model:${model.providerID}:${model.modelID}`).row();
  };

  favorites.forEach((model) => addButton(model, "⭐"));
  recent.forEach((model) => addButton(model, "🕘"));

  return keyboard;
}

/**
 * Show model selection menu
 * @param ctx grammY context
 */
export async function showModelSelectionMenu(ctx: Context): Promise<void> {
  try {
    const currentModel = fetchCurrentModel();
    const catalog = await getAvailableCatalogModels();
    const totalPages = Math.max(1, Math.ceil(catalog.length / MODEL_PAGE_SIZE));
    const keyboard = await buildModelSelectionMenu(currentModel, undefined, 0, catalog);

    if (keyboard.inline_keyboard.length === 0) {
      await ctx.reply(t("model.menu.empty"));
      return;
    }

    const text = buildCatalogMenuText(0, totalPages);

    await replyWithInlineMenu(ctx, {
      menuKind: "model",
      text,
      keyboard,
    });
  } catch (err) {
    logger.error("[ModelHandler] Error showing model menu:", err);
    await ctx.reply(t("model.menu.error"));
  }
}
