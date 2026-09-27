import { API_BASE_URL, apiClient } from './client';
import type {
    Statement,
    StatementDetail,
    TransactionSchema,
    TransactionsResponse,
    UploadResponse,
    StatementSummary,
    PaginatedResponse
} from '../types';

export const statementsApi = {
    // Upload PDF
    upload: async (file: File): Promise<UploadResponse> => {
        const formData = new FormData();
        formData.append('file', file);

        const response = await apiClient.post('/upload', formData, {
            headers: {
                'Content-Type': 'multipart/form-data',
            },
        });
        return response.data;
    },

    // List statements
    list: async (params?: {
        page?: number;
        limit?: number;
        status?: string;
        search?: string;
    }): Promise<PaginatedResponse<Statement>> => {
        const response = await apiClient.get('/statements', { params });
        return response.data;
    },

    // Get statement details
    get: async (statementId: number): Promise<StatementDetail> => {
        const response = await apiClient.get(`/statements/${statementId}`);
        return response.data;
    },

    // Get statement file URL
    getFileUrl: (statementId: number): string => `${API_BASE_URL}/statements/${statementId}/file`,

    // Delete statement
    delete: async (statementId: number): Promise<void> => {
        await apiClient.delete(`/statements/${statementId}`);
    },

    // Get transaction schema
    getSchema: async (statementId: number): Promise<TransactionSchema> => {
        const response = await apiClient.get(`/statements/${statementId}/schema`);
        return response.data;
    },

    // Get statement summary
    getSummary: async (statementId: number): Promise<StatementSummary> => {
        const response = await apiClient.get(`/statements/${statementId}/summary`);
        return response.data;
    },

    // Get transactions for a statement
    getTransactions: async (
        statementId: number,
        params?: {
            page?: number;
            limit?: number;
            type?: 'credit' | 'debit';
            date_from?: string;
            date_to?: string;
            min_amount?: number;
            max_amount?: number;
            search?: string;
            sort_by?: 'date' | 'amount';
            sort_order?: 'asc' | 'desc';
        }
    ): Promise<TransactionsResponse> => {
        const response = await apiClient.get(`/statements/${statementId}/transactions`, { params });
        return response.data;
    },

    // Search all transactions
    searchTransactions: async (params?: {
        page?: number;
        limit?: number;
        type?: 'credit' | 'debit';
        date_from?: string;
        date_to?: string;
        min_amount?: number;
        max_amount?: number;
        search?: string;
        statement_ids?: string;
        sort_by?: 'date' | 'amount';
        sort_order?: 'asc' | 'desc';
    }): Promise<TransactionsResponse> => {
        const response = await apiClient.get('/transactions', { params });
        return response.data;
    },

    // Get statement metadata
    getMetadata: async (statementId: number): Promise<any> => {
        const response = await apiClient.get(`/statements/${statementId}/metadata`);
        return response.data;
    },

    // Update transaction schema
    updateSchema: async (
        statementId: number,
        columnMetadata: Record<string, { type: string; display_name: string }>
    ): Promise<{ success: boolean; message: string; schema: TransactionSchema }> => {
        const response = await apiClient.put(`/statements/${statementId}/schema`, {
            column_metadata: columnMetadata,
        });
        return response.data;
    },
};
