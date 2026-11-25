import React, { useEffect, useMemo, useRef, useState } from "react";
import { apiRequest } from "../../api/client";
import { bilingual, UiLanguage } from "../../bridge/useWorkbenchBridge";
import {
  REVIEW_TAG_GROUPS,
  showWorkbenchToast,
  TagCatalogItem,
} from "./reviewHelpers";

export interface ReviewTagSelectorProps {
  catalog: TagCatalogItem[];
  selectedTags: string[];
  onChange: (nextTags: string[]) => void;
  lang: UiLanguage;
  disabled?: boolean;
  canCreateCustom?: boolean;
  onCatalogRefresh?: () => void;
}

export const ReviewTagSelector: React.FC<ReviewTagSelectorProps> = ({
  catalog,
  selectedTags,
  onChange,
  lang,
  disabled = false,
  canCreateCustom = false,
  onCatalogRefresh,
}) => {
  const [openGroup, setOpenGroup] = useState<string | null>(null);
  const [addingGroup, setAddingGroup] = useState<string | null>(null);
  const [newTagLabel, setNewTagLabel] = useState("");
  const [creating, setCreating] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);

  const selectedSet = useMemo(() => new Set(selectedTags), [selectedTags]);

  useEffect(() => {
    if (!openGroup) return;
    const handleOutside = (event: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setOpenGroup(null);
        setAddingGroup(null);
      }
    };
    const handleEsc = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpenGroup(null);
        setAddingGroup(null);
      }
    };
    document.addEventListener("mousedown", handleOutside);
    document.addEventListener("keydown", handleEsc);
    return () => {
      document.removeEventListener("mousedown", handleOutside);
      document.removeEventListener("keydown", handleEsc);
    };
  }, [openGroup]);

  const byGroup = useMemo(() => {
    const map = new Map<string, TagCatalogItem[]>();
    for (const def of REVIEW_TAG_GROUPS) map.set(def.group, []);
    for (const item of catalog) {
      const g = item.group || "";
      if (map.has(g)) map.get(g)!.push(item);
    }
    return map;
  }, [catalog]);

  const legacyTags = useMemo(() => {
    const known = new Set(catalog.map((c) => c.key));
    return selectedTags.filter((k) => !known.has(k));
  }, [catalog, selectedTags]);

  const toggleTag = (key: string) => {
    if (disabled) return;
    if (selectedSet.has(key)) onChange(selectedTags.filter((k) => k !== key));
    else onChange([...selectedTags, key]);
  };

  const handleCreateCustomTag = async (section: string, group: string) => {
    const label = newTagLabel.trim();
    if (!label || creating) return;
    setCreating(true);
    try {
      const res = await apiRequest<{ item?: TagCatalogItem; tag?: TagCatalogItem }>("/api/review-tags", {
        method: "POST",
        body: { section, group, label },
      });
      const createdKey = res.item?.key || res.tag?.key;
      setNewTagLabel("");
      setAddingGroup(null);
      onCatalogRefresh?.();
      if (createdKey && !selectedSet.has(createdKey)) {
        onChange([...selectedTags, createdKey]);
      }
      showWorkbenchToast(bilingual(lang, "已新增自定义标签。", "Custom tag created."));
    } catch (err) {
      showWorkbenchToast(
        err instanceof Error ? err.message : bilingual(lang, "新增标签失败。", "Failed to create tag."),
        true,
      );
    } finally {
      setCreating(false);
    }
  };

  const sections = [
    { key: "scene", zh: "场景", en: "Scene", groups: REVIEW_TAG_GROUPS.slice(0, 2) },
    {
      key: "interaction_decision",
      zh: "触发判定",
      en: "Trigger decision",
      groups: REVIEW_TAG_GROUPS.slice(2, 4),
    },
    { key: "egress", zh: "如何驶离", en: "Egress", groups: REVIEW_TAG_GROUPS.slice(4, 6) },
  ];

  return (
    <div ref={containerRef} className="ra-tag-selector-root">
      {sections.map((sec) => (
        <div key={sec.key} className="ra-tag-axis-block">
          <div className="review-tag-axis-title">{bilingual(lang, sec.zh, sec.en)}</div>
          <div className="ra-tag-group-pair">
            {sec.groups.map((def) => {
              const items = byGroup.get(def.group) || [];
              const activeItems = items.filter((i) => selectedSet.has(i.key));
              const isOpen = openGroup === def.group;
              return (
                <div
                  key={def.group}
                  className={`ra-tag-dropdown${isOpen ? " is-open" : ""}${activeItems.length ? " has-selection" : ""}`}
                >
                  <button
                    type="button"
                    className="ra-tag-dropdown-trigger"
                    aria-expanded={isOpen}
                    disabled={disabled}
                    onClick={() => setOpenGroup(isOpen ? null : def.group)}
                  >
                    <span className="ra-tag-group-name">{bilingual(lang, def.zh, def.en)}</span>
                    <span className="ra-tag-group-right">
                      <kbd className="review-control-shortcut" aria-hidden="true">
                        {def.shortcut}
                      </kbd>
                      <span className="ra-tag-count-pill">
                        {bilingual(lang, `${activeItems.length} 项`, `${activeItems.length}`)}
                      </span>
                    </span>
                  </button>

                  {isOpen && (
                    <div className="ra-tag-dropdown-panel" role="group" aria-label={bilingual(lang, def.zh, def.en)}>
                      <div className="ra-tag-options-list">
                        {items.length === 0 ? (
                          <div className="muted ra-tag-empty">
                            {bilingual(lang, "暂无标签选项", "No tags available")}
                          </div>
                        ) : (
                          items.map((item) => {
                            const checked = selectedSet.has(item.key);
                            const text =
                              lang === "en" && item.label_en ? item.label_en : item.label || item.key;
                            return (
                              <label key={item.key} className="review-tag-option-row ra-tag-option-row">
                                <input
                                  type="checkbox"
                                  checked={checked}
                                  disabled={disabled}
                                  onChange={() => toggleTag(item.key)}
                                />
                                <span title={item.hint || text}>{text}</span>
                              </label>
                            );
                          })
                        )}
                      </div>

                      {canCreateCustom && !disabled && (
                        <div className="ra-tag-create-footer">
                          {addingGroup === def.group ? (
                            <div className="ra-tag-create-inline">
                              <input
                                type="text"
                                maxLength={40}
                                value={newTagLabel}
                                onChange={(e) => setNewTagLabel(e.target.value)}
                                placeholder={bilingual(lang, "输入新标签名称", "New tag label")}
                                onKeyDown={(e) => {
                                  if (e.key === "Enter") {
                                    e.preventDefault();
                                    void handleCreateCustomTag(def.section, def.group);
                                  }
                                }}
                              />
                              <button
                                type="button"
                                className="button button-primary"
                                disabled={creating || !newTagLabel.trim()}
                                onClick={() => void handleCreateCustomTag(def.section, def.group)}
                              >
                                {bilingual(lang, "添加", "Add")}
                              </button>
                            </div>
                          ) : (
                            <button
                              type="button"
                              className="button button-quiet"
                              onClick={() => {
                                setAddingGroup(def.group);
                                setNewTagLabel("");
                              }}
                            >
                              + {bilingual(lang, `新增${def.zh}标签`, `Add ${def.en} tag`)}
                            </button>
                          )}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      ))}

      {selectedTags.length > 0 && (
        <div className="ra-selected-tags-bar" aria-label={bilingual(lang, "已选标签", "Selected tags")}>
          {selectedTags.map((key) => {
            const item = catalog.find((c) => c.key === key);
            const text =
              lang === "en" && item?.label_en ? item.label_en : item?.label || key;
            return (
              <span key={key} className="analysis-chip tag-chip ra-selected-tag-chip">
                <span>{text}</span>
                {!disabled && (
                  <button
                    type="button"
                    aria-label={bilingual(lang, `移除 ${text}`, `Remove ${text}`)}
                    onClick={() => toggleTag(key)}
                  >
                    ×
                  </button>
                )}
              </span>
            );
          })}
          {legacyTags.length > 0 && (
            <small className="muted">
              {bilingual(lang, `含 ${legacyTags.length} 个历史标签`, `Includes ${legacyTags.length} legacy tag(s)`)}
            </small>
          )}
        </div>
      )}
    </div>
  );
};
