package com.owencli.contextos.store;

import com.owencli.contextos.core.model.*;

import java.util.List;
import java.util.Optional;
import java.util.concurrent.CompletableFuture;

/**
 * 存储提供商 SPI — 参考 DeerFlow Checkpointer 多后端 + storage_class 设计。
 * <p>
 * 各实现：
 * - {@code SQLiteStoreProvider} — 默认，嵌入式
 * - {@code H2StoreProvider} — 测试用
 * - {@code PostgreSQLStoreProvider} — 生产部署
 */
public interface StoreProvider {

    /** 提供商名称：sqlite / postgresql / h2 */
    String name();

    /** 当前环境是否可用（驱动、连接等） */
    boolean isAvailable();

    /** 打开一个存储会话 */
    CompletableFuture<StoreSession> openSession();
}
