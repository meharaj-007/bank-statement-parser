import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Trash2, AlertCircle, FileText, Table, Activity, Eye, Download } from 'lucide-react';
import { statementsApi } from '@/api/statements';
import TransactionTable from '@/components/TransactionTable';
import MetadataViewer from '@/components/MetadataViewer';
import type { StatementDetail as StatementDetailType } from '@/types';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Spinner } from '@/components/ui/spinner';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';

const POLL_INTERVAL_MS = 2000;

const isProcessing = (status?: string) => status === 'pending' || status === 'processing';

export default function StatementDetail() {
    const { id } = useParams<{ id: string }>();
    const navigate = useNavigate();
    const [statement, setStatement] = useState<StatementDetailType | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        if (id) {
            loadStatement(parseInt(id));
        }
    }, [id]);

    // Processing runs in the background worker; poll until it settles
    useEffect(() => {
        if (!id || !isProcessing(statement?.status)) return;

        const timer = setTimeout(async () => {
            try {
                setStatement(await statementsApi.get(parseInt(id)));
            } catch (err) {
                console.error(err);
            }
        }, POLL_INTERVAL_MS);
        return () => clearTimeout(timer);
    }, [id, statement]);

    const loadStatement = async (statementId: number) => {
        setLoading(true);
        setError(null);

        try {
            const data = await statementsApi.get(statementId);
            setStatement(data);
        } catch (err: any) {
            setError('Failed to load statement');
            console.error(err);
        } finally {
            setLoading(false);
        }
    };

    const handleDelete = async () => {
        if (!id) return;
        if (!confirm('Are you sure you want to delete this statement?')) return;

        try {
            await statementsApi.delete(parseInt(id));
            navigate('/statements');
        } catch (err) {
            alert('Failed to delete statement');
        }
    };

    const formatFieldName = (key: string): string => {
        // Handle special cases
        const specialCases: Record<string, string> = {
            'statement_period_start': 'Period Start',
            'statement_period_end': 'Period End',
            'opening_balance': 'Opening Balance',
            'closing_balance': 'Closing Balance',
            'account_holder_name': 'Account Holder',
            'account_number': 'Account Number',
            'bank_name': 'Bank Name',
        };

        return specialCases[key] || key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
    };

    const formatFieldValue = (key: string, value: any): string => {
        // Format currency values
        if (key === 'opening_balance' || key === 'closing_balance') {
            return `${value} ${statement?.bank_details?.currency || ''}`.trim();
        }

        // Format date values
        if (key === 'statement_period_start' || key === 'statement_period_end') {
            try {
                const date = new Date(value);
                return date.toLocaleDateString('en-US', {
                    year: 'numeric',
                    month: 'long',
                    day: 'numeric'
                });
            } catch {
                return String(value);
            }
        }

        return String(value);
    };

    const calculateStatementPeriod = (startDate: string | null, endDate: string | null): string | null => {
        if (!startDate || !endDate) return null;

        const start = new Date(startDate);
        const end = new Date(endDate);

        // Calculate difference
        let years = end.getFullYear() - start.getFullYear();
        let months = end.getMonth() - start.getMonth();
        let days = end.getDate() - start.getDate();

        // Adjust for negative days
        if (days < 0) {
            months--;
            const lastMonth = new Date(end.getFullYear(), end.getMonth(), 0);
            days += lastMonth.getDate();
        }

        // Adjust for negative months
        if (months < 0) {
            years--;
            months += 12;
        }

        // Build human-readable string
        const parts: string[] = [];
        if (years > 0) parts.push(`${years} year${years !== 1 ? 's' : ''}`);
        if (months > 0) parts.push(`${months} month${months !== 1 ? 's' : ''}`);
        if (days > 0 && years === 0) parts.push(`${days} day${days !== 1 ? 's' : ''}`);

        return parts.length > 0 ? parts.join(', ') : '0 days';
    };

    const renderInfoCard = (title: string, data: Record<string, any> | null) => {
        if (!data) return null;

        const entries = Object.entries(data).filter(([_, value]) => value !== null && value !== '');

        if (entries.length === 0) return null;

        // Calculate statement period for bank details
        const statementPeriod = title === 'Bank Details'
            ? calculateStatementPeriod(data.statement_period_start, data.statement_period_end)
            : null;

        return (
            <Card>
                <CardHeader>
                    <CardTitle>{title}</CardTitle>
                </CardHeader>
                <CardContent>
                    <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                        {entries.map(([key, value]) => (
                            <div key={key}>
                                <dt className="text-sm font-medium text-gray-500">
                                    {formatFieldName(key)}
                                </dt>
                                <dd className="mt-1 text-sm text-gray-900">{formatFieldValue(key, value)}</dd>
                            </div>
                        ))}
                        {statementPeriod && (
                            <div>
                                <dt className="text-sm font-medium text-gray-500">
                                    Statement Period Duration
                                </dt>
                                <dd className="mt-1 text-sm text-gray-900 font-semibold">{statementPeriod}</dd>
                            </div>
                        )}
                    </dl>
                </CardContent>
            </Card>
        );
    };

    const getStatusBadge = (status: string) => {
        const variants: Record<string, any> = {
            completed: 'success',
            processing: 'default',
            failed: 'destructive',
            pending: 'warning',
        };
        return <Badge variant={variants[status] || 'secondary'} className="capitalize">{status}</Badge>;
    };

    if (loading) {
        return (
            <div className="flex justify-center py-12">
                <Spinner size="lg" />
            </div>
        );
    }

    if (error || !statement) {
        return (
            <div className="px-4 sm:px-0">
                <div className="p-4 bg-red-50 border border-red-200 rounded-md">
                    <p className="text-sm text-red-800">{error || 'Statement not found'}</p>
                </div>
            </div>
        );
    }

    return (
        <div className="px-4 sm:px-0">
            {/* Header */}
            <div className="flex items-start justify-between mb-8">
                <div>
                    <h1 className="text-3xl font-bold text-gray-900">{statement.filename}</h1>
                    <p className="mt-2 text-gray-600">
                        Uploaded on {new Date(statement.upload_date).toLocaleDateString()}
                    </p>
                </div>
                <div className="flex gap-2">
                    {getStatusBadge(statement.status)}
                    <Button variant="destructive" onClick={handleDelete}>
                        <Trash2 className="h-4 w-4 mr-2" />
                        Delete
                    </Button>
                </div>
            </div>

            {/* Failed Status */}
            {statement.status === 'failed' && (
                <Card className="mb-6 border-red-200 bg-red-50">
                    <CardContent className="pt-6">
                        <div className="flex items-start">
                            <AlertCircle className="h-5 w-5 mr-3 text-red-600 mt-0.5" />
                            <div>
                                <p className="text-sm font-medium text-red-900">Processing failed</p>
                                <p className="text-sm text-red-700 mt-1">
                                    {statement.error_message || 'An error occurred while processing this statement.'}
                                </p>
                            </div>
                        </div>
                    </CardContent>
                </Card>
            )}

            {/* Processing Status */}
            {isProcessing(statement.status) && (
                <Card className="mb-6 border-blue-200 bg-blue-50">
                    <CardContent className="pt-6">
                        <div className="flex items-center">
                            <Spinner size="sm" className="mr-3" />
                            <div>
                                <p className="text-sm font-medium text-blue-900">
                                    {statement.status === 'pending' ? 'Waiting for a worker' : 'Extracting transactions'}
                                </p>
                                <p className="text-sm text-blue-700 mt-1">
                                    {statement.page_count
                                        ? `Reading ${statement.page_count} page${statement.page_count === 1 ? '' : 's'}. This page updates automatically.`
                                        : 'This page updates automatically.'}
                                </p>
                            </div>
                        </div>
                    </CardContent>
                </Card>
            )}

            {/* Completed, but some pages could not be read */}
            {statement.status === 'completed' && statement.error_message && (
                <Card className="mb-6 border-amber-200 bg-amber-50">
                    <CardContent className="pt-6">
                        <div className="flex items-start">
                            <AlertCircle className="h-5 w-5 mr-3 text-amber-600 mt-0.5" />
                            <p className="text-sm text-amber-900">{statement.error_message}</p>
                        </div>
                    </CardContent>
                </Card>
            )}

            {/* Tabs - File viewing available for all, other tabs only for completed.
                Keyed on status so the default tab resets once processing finishes. */}
            <Tabs key={statement.status} defaultValue={statement.status === 'completed' ? 'overview' : 'file'} className="w-full">
                <TabsList className="mb-6">
                    {statement.status === 'completed' && (
                        <TabsTrigger value="overview">
                            <FileText className="h-4 w-4 mr-2" />
                            Overview
                        </TabsTrigger>
                    )}
                    <TabsTrigger value="file">
                        <Eye className="h-4 w-4 mr-2" />
                        View PDF
                    </TabsTrigger>
                    {statement.status === 'completed' && (
                        <>
                            <TabsTrigger value="transactions">
                                <Table className="h-4 w-4 mr-2" />
                                Transactions
                            </TabsTrigger>
                            <TabsTrigger value="metadata">
                                <Activity className="h-4 w-4 mr-2" />
                                Metadata & Logs
                            </TabsTrigger>
                        </>
                    )}
                </TabsList>

                {statement.status === 'completed' && (
                    <TabsContent value="overview">
                        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
                            {renderInfoCard('Customer Details', statement.customer_details)}
                            {renderInfoCard('Bank Details', statement.bank_details)}
                        </div>
                    </TabsContent>
                )}

                <TabsContent value="file">
                    <Card>
                        <CardHeader>
                            <div className="flex items-center justify-between">
                                <CardTitle>Original PDF Statement</CardTitle>
                                <Button
                                    variant="outline"
                                    size="sm"
                                    onClick={() => {
                                        const fileUrl = statementsApi.getFileUrl(statement.id);
                                        const link = document.createElement('a');
                                        link.href = fileUrl;
                                        link.download = statement.filename;
                                        link.click();
                                    }}
                                >
                                    <Download className="h-4 w-4 mr-2" />
                                    Download
                                </Button>
                            </div>
                        </CardHeader>
                        <CardContent>
                            <div className="w-full border rounded-lg overflow-hidden bg-gray-50">
                                <iframe
                                    src={statementsApi.getFileUrl(statement.id)}
                                    className="w-full h-[800px] border-0"
                                    title="PDF Viewer"
                                />
                            </div>
                        </CardContent>
                    </Card>
                </TabsContent>

                {statement.status === 'completed' && (
                    <>
                        <TabsContent value="transactions">
                            {id && <TransactionTable statementId={parseInt(id)} />}
                        </TabsContent>

                        <TabsContent value="metadata">
                            {id && <MetadataViewer statementId={parseInt(id)} />}
                        </TabsContent>
                    </>
                )}
            </Tabs>
        </div>
    );
}
