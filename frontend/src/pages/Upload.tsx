import { useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Upload as UploadIcon, FileCheck, X, FileText, CheckCircle2, AlertCircle, Info } from 'lucide-react';
import { statementsApi } from '@/api/statements';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';

const MAX_FILE_SIZE = 10 * 1024 * 1024; // 10MB

export default function Upload() {
    const [file, setFile] = useState<File | null>(null);
    const [uploading, setUploading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [dragActive, setDragActive] = useState(false);
    const [uploadProgress, setUploadProgress] = useState(0);
    const navigate = useNavigate();

    const validateFile = (file: File): string | null => {
        if (file.type !== 'application/pdf') {
            return 'Please upload a PDF file. Other file types are not supported.';
        }
        if (file.size > MAX_FILE_SIZE) {
            return `File size exceeds the maximum limit of ${(MAX_FILE_SIZE / 1024 / 1024).toFixed(0)}MB.`;
        }
        if (file.size === 0) {
            return 'The selected file is empty. Please choose a valid PDF file.';
        }
        return null;
    };

    const handleDrag = useCallback((e: React.DragEvent) => {
        e.preventDefault();
        e.stopPropagation();
        if (e.type === 'dragenter' || e.type === 'dragover') {
            setDragActive(true);
        } else if (e.type === 'dragleave') {
            setDragActive(false);
        }
    }, []);

    const handleDrop = useCallback((e: React.DragEvent) => {
        e.preventDefault();
        e.stopPropagation();
        setDragActive(false);
        setError(null);

        if (e.dataTransfer.files && e.dataTransfer.files[0]) {
            const droppedFile = e.dataTransfer.files[0];
            const validationError = validateFile(droppedFile);
            if (validationError) {
                setError(validationError);
            } else {
                setFile(droppedFile);
            }
        }
    }, []);

    const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        setError(null);
        if (e.target.files && e.target.files[0]) {
            const selectedFile = e.target.files[0];
            const validationError = validateFile(selectedFile);
            if (validationError) {
                setError(validationError);
                e.target.value = ''; // Reset input
            } else {
                setFile(selectedFile);
            }
        }
    };

    const handleRemoveFile = () => {
        setFile(null);
        setError(null);
        setUploadProgress(0);
    };

    const handleUpload = async () => {
        if (!file) return;

        setUploading(true);
        setError(null);
        setUploadProgress(0);

        try {
            // Simulate progress for better UX
            const progressInterval = setInterval(() => {
                setUploadProgress((prev) => {
                    if (prev >= 90) {
                        clearInterval(progressInterval);
                        return 90;
                    }
                    return prev + 10;
                });
            }, 200);

            const response = await statementsApi.upload(file);
            clearInterval(progressInterval);
            setUploadProgress(100);
            
            // Small delay to show completion
            setTimeout(() => {
                navigate(`/statements/${response.statement_id}`);
            }, 500);
        } catch (err: any) {
            // Same file uploaded before: open the existing statement instead
            const existingId = err.response?.status === 409 && err.response?.data?.existing_statement_id;
            if (existingId) {
                navigate(`/statements/${existingId}`);
                return;
            }
            setError(err.response?.data?.message || err.message || 'Failed to upload file. Please try again.');
            setUploading(false);
            setUploadProgress(0);
        }
    };

    const formatFileSize = (bytes: number): string => {
        if (bytes < 1024) return bytes + ' B';
        if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(2) + ' KB';
        return (bytes / 1024 / 1024).toFixed(2) + ' MB';
    };

    return (
        <div className="w-full">
            <div className="mb-8">
                <h1 className="text-3xl font-bold text-gray-900">Upload Bank Statement</h1>
                <p className="mt-2 text-gray-600">
                    Upload a PDF bank statement to extract transaction data automatically using AI.
                </p>
            </div>

            <div className="w-full space-y-6">
                {/* Main Upload Card */}
                <Card>
                    <CardContent className="pt-6">
                        {/* Drag and Drop Zone */}
                        <div
                            className={`relative border-2 border-dashed rounded-xl p-12 text-center transition-all duration-200 ${
                                dragActive
                                    ? 'border-blue-500 bg-blue-50 scale-[1.02]'
                                    : 'border-gray-300 hover:border-gray-400 bg-gray-50/50'
                            } ${uploading ? 'pointer-events-none opacity-60' : ''}`}
                            onDragEnter={handleDrag}
                            onDragLeave={handleDrag}
                            onDragOver={handleDrag}
                            onDrop={handleDrop}
                        >
                            <input
                                type="file"
                                accept=".pdf,application/pdf"
                                onChange={handleFileChange}
                                className="hidden"
                                id="file-upload"
                                disabled={uploading}
                            />

                            {!file ? (
                                <div className="space-y-4">
                                    <div className="flex justify-center">
                                        <div className="rounded-full bg-gray-100 p-4">
                                            <UploadIcon className="h-10 w-10 text-gray-400" />
                                        </div>
                                    </div>
                                    <div>
                                        <label
                                            htmlFor="file-upload"
                                            className="cursor-pointer text-blue-600 hover:text-blue-500 font-semibold text-base transition-colors"
                                        >
                                            Choose a PDF file
                                        </label>
                                        <span className="text-gray-500"> or drag and drop here</span>
                                    </div>
                                    <div className="flex items-center justify-center gap-2 text-xs text-gray-500">
                                        <FileText className="h-3 w-3" />
                                        <span>PDF format only • Max size: {(MAX_FILE_SIZE / 1024 / 1024).toFixed(0)}MB</span>
                                    </div>
                                </div>
                            ) : (
                                <div className="space-y-4">
                                    <div className="flex justify-center">
                                        <div className="rounded-full bg-green-100 p-4">
                                            <FileCheck className="h-10 w-10 text-green-600" />
                                        </div>
                                    </div>
                                    <div className="space-y-2">
                                        <p className="text-base font-semibold text-gray-900 truncate max-w-md mx-auto">
                                            {file.name}
                                        </p>
                                        <div className="flex items-center justify-center gap-3 text-sm text-gray-600">
                                            <Badge variant="secondary" className="text-xs">
                                                {formatFileSize(file.size)}
                                            </Badge>
                                            <Badge variant="success" className="text-xs">
                                                <FileCheck className="h-3 w-3 mr-1" />
                                                Valid PDF
                                            </Badge>
                                        </div>
                                    </div>
                                    {!uploading && (
                                        <Button
                                            type="button"
                                            variant="ghost"
                                            size="sm"
                                            onClick={handleRemoveFile}
                                            className="mt-2"
                                        >
                                            <X className="h-4 w-4 mr-2" />
                                            Remove File
                                        </Button>
                                    )}
                                </div>
                            )}
                        </div>

                        {/* Upload Progress */}
                        {uploading && (
                            <div className="mt-6 space-y-3">
                                <div className="flex items-center justify-between text-sm">
                                    <span className="text-gray-600 font-medium">Uploading and processing...</span>
                                    <span className="text-gray-500">{uploadProgress}%</span>
                                </div>
                                <div className="w-full bg-gray-200 rounded-full h-2 overflow-hidden">
                                    <div
                                        className="bg-blue-600 h-2 rounded-full transition-all duration-300 ease-out"
                                        style={{ width: `${uploadProgress}%` }}
                                    />
                                </div>
                            </div>
                        )}

                        {/* Error Message */}
                        {error && (
                            <div className="mt-4 p-4 bg-red-50 border border-red-200 rounded-lg flex items-start gap-3">
                                <AlertCircle className="h-5 w-5 text-red-600 shrink-0 mt-0.5" />
                                <div className="flex-1">
                                    <p className="text-sm font-medium text-red-800">Upload Error</p>
                                    <p className="text-sm text-red-700 mt-1">{error}</p>
                                </div>
                                <Button
                                    type="button"
                                    variant="ghost"
                                    size="icon"
                                    onClick={() => setError(null)}
                                    className="h-6 w-6 text-red-600 hover:text-red-700 hover:bg-red-100"
                                >
                                    <X className="h-4 w-4" />
                                </Button>
                            </div>
                        )}

                        {/* Upload Button */}
                        {!uploading && (
                            <div className="mt-6">
                                <Button
                                    type="button"
                                    onClick={handleUpload}
                                    disabled={!file}
                                    className="w-full"
                                    size="lg"
                                >
                                    <UploadIcon className="h-4 w-4 mr-2" />
                                    Upload and Process Statement
                                </Button>
                            </div>
                        )}
                    </CardContent>
                </Card>

                {/* Info Cards */}
                <div className="grid gap-6 md:grid-cols-2">
                    {/* Process Info */}
                    <Card className="border-blue-200 bg-blue-50/50">
                        <CardHeader>
                            <div className="flex items-center gap-2">
                                <Info className="h-5 w-5 text-blue-600" />
                                <CardTitle className="text-base text-blue-900">What happens next?</CardTitle>
                            </div>
                        </CardHeader>
                        <CardContent>
                            <ul className="space-y-3 text-sm text-blue-900">
                                <li className="flex items-start gap-2">
                                    <CheckCircle2 className="h-4 w-4 text-blue-600 shrink-0 mt-0.5" />
                                    <span>PDF pages are extracted as high-quality images</span>
                                </li>
                                <li className="flex items-start gap-2">
                                    <CheckCircle2 className="h-4 w-4 text-blue-600 shrink-0 mt-0.5" />
                                    <span>AI analyzes each page to extract transaction data</span>
                                </li>
                                <li className="flex items-start gap-2">
                                    <CheckCircle2 className="h-4 w-4 text-blue-600 shrink-0 mt-0.5" />
                                    <span>Customer details, bank info, and transactions are saved</span>
                                </li>
                                <li className="flex items-start gap-2">
                                    <CheckCircle2 className="h-4 w-4 text-blue-600 shrink-0 mt-0.5" />
                                    <span>You'll be redirected to view the extracted data</span>
                                </li>
                            </ul>
                        </CardContent>
                    </Card>

                    {/* Requirements */}
                    <Card className="border-gray-200 bg-gray-50/50">
                        <CardHeader>
                            <div className="flex items-center gap-2">
                                <FileText className="h-5 w-5 text-gray-600" />
                                <CardTitle className="text-base text-gray-900">File Requirements</CardTitle>
                            </div>
                        </CardHeader>
                        <CardContent>
                            <ul className="space-y-3 text-sm text-gray-700">
                                <li className="flex items-start gap-2">
                                    <span className="text-gray-400 mt-0.5">•</span>
                                    <span>File format: PDF only</span>
                                </li>
                                <li className="flex items-start gap-2">
                                    <span className="text-gray-400 mt-0.5">•</span>
                                    <span>Maximum file size: {(MAX_FILE_SIZE / 1024 / 1024).toFixed(0)}MB</span>
                                </li>
                                <li className="flex items-start gap-2">
                                    <span className="text-gray-400 mt-0.5">•</span>
                                    <span>Supported: All major bank statement formats</span>
                                </li>
                                <li className="flex items-start gap-2">
                                    <span className="text-gray-400 mt-0.5">•</span>
                                    <span>Processing time: Usually 30-60 seconds</span>
                                </li>
                            </ul>
                        </CardContent>
                    </Card>
                </div>
            </div>
        </div>
    );
}
