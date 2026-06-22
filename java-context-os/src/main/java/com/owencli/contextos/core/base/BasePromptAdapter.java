package com.owencli.contextos.core.base;

import com.owencli.contextos.core.model.OptimizedContext;
import com.owencli.contextos.core.model.PackagedContext;

/**
 * Base interface for LLM prompt adapters.
 */
public interface BasePromptAdapter {

    String getProvider();

    PackagedContext pack(OptimizedContext context);
}
