package com.owencli.contextos.packager.adapters;

import com.owencli.contextos.core.model.OptimizedContext;
import com.owencli.contextos.core.model.PackagedContext;

public interface BasePromptAdapter {
    String getProvider();
    PackagedContext pack(OptimizedContext context);
}
