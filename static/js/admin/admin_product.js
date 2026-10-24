document.addEventListener('DOMContentLoaded', () => {

    /* ==========================================================
       1. GLOBAL REFERENCES & SETUP
       ========================================================== */
    const regModal = document.getElementById('registerAssetModal');
    const histModal = document.getElementById('assetHistoryModal');
    const editModal = document.getElementById('editAssetModal');
    
    const addEquipmentBtn = document.getElementById('add-equipment-btn');
    const inventoryTable = document.getElementById('inventory-table');
    const allRows = document.querySelectorAll('#inventory-table tbody tr');


    /* ==========================================================
       2. ACTION DROPDOWN TOGGLE LOGIC
       ========================================================== */
    allRows.forEach(row => {
        row.addEventListener('click', function(e) {
            if (e.target.closest('.asset-action-btn')) return;

            const isActive = this.classList.contains('row-active');

            allRows.forEach(r => r.classList.remove('row-active'));
            document.querySelectorAll('.action-dropdown').forEach(d => d.classList.remove('active'));

            if (!isActive) {
                this.classList.add('row-active');
            }
        });
    });

    document.querySelectorAll('.more-trigger').forEach(trigger => {
        trigger.addEventListener('click', function(e) {
            e.stopPropagation();

            const parentDropdown = this.closest('.action-dropdown');
            const parentRow = this.closest('tr');
            const menu = parentDropdown.querySelector('.dropdown-menu');

            document.querySelectorAll('.action-dropdown').forEach(d => {
                if (d !== parentDropdown) d.classList.remove('active');
            });

            parentDropdown.classList.toggle('active');

            // Position the dropdown using fixed coords from the trigger button
            if (parentDropdown.classList.contains('active') && menu) {
                const rect = this.getBoundingClientRect();
                menu.style.top = (rect.bottom + 4) + 'px';
                menu.style.left = (rect.right - menu.offsetWidth - 4) + 'px';
                
                // Adjust if menu goes off screen bottom
                const menuBottom = rect.bottom + 4 + menu.offsetHeight;
                if (menuBottom > window.innerHeight) {
                    menu.style.top = (rect.top - menu.offsetHeight - 4) + 'px';
                }
            }

            allRows.forEach(r => r.classList.remove('row-active'));
            parentRow.classList.add('row-active');
        });
    });

    document.addEventListener('click', (e) => {
        if (!e.target.closest('#inventory-table')) {
            allRows.forEach(r => r.classList.remove('row-active'));
            document.querySelectorAll('.action-dropdown').forEach(d => d.classList.remove('active'));
        }
    });


    /* ==========================================================
       3. HISTORY MODAL LOGIC
       ========================================================== */
    function getMarkerClass(action) {
        const actionLower = action.toLowerCase();
        if (actionLower.includes('return') || actionLower.includes('sold')) return 'warning';
        if (actionLower.includes('clean') || actionLower.includes('ready') || actionLower.includes('restock')) return 'ready';
        if (actionLower.includes('delete') || actionLower.includes('repair')) return 'danger';
        return 'info';
    }

    document.addEventListener('click', async (e) => {
        const btn = e.target.closest('.logs'); 
        if (!btn) return;

        const row = btn.closest('tr');
        if (!row) return;

        const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
        }[c]));

        const productId = btn.dataset.productId;
        const equipmentName = row.cells[1].innerText;
        const model = row.cells[2].innerText;

        document.getElementById('history-asset-id').innerText = `${equipmentName} ${model} • ID: ${productId}`;

        const container = document.querySelector('.history-timeline-container');
        container.innerHTML = "<p>Loading...</p>";

        try {
            const res = await fetch(`/admin/product/${productId}/history`);
            const logs = await res.json();

            if (!logs.length) {
                container.innerHTML = "<p>No history available.</p>";
            } else {
                container.innerHTML = logs.map(log => {
                    const refLine = log.reference
                        ? `<div style="font-size:0.7rem;color:#64748b;font-weight:700;margin-bottom:3px;">
                               ${escapeHtml(log.reference)}${log.reason ? ` · ${escapeHtml(log.reason)}` : ''}
                           </div>`
                        : '';
                    const balanceLine = (log.balance_after !== null && log.balance_after !== undefined)
                        ? `<span><i class="material-symbols-rounded" style="font-size:14px; vertical-align:middle;">account_balance_wallet</i> Balance: ${escapeHtml(log.balance_after)}</span>`
                        : '';
                    return `
                    <div class="timeline-item">
                        <div class="timeline-marker ${getMarkerClass(log.action)}"></div>
                        <div class="timeline-content">
                            <div class="timeline-header">
                                <span class="event-title">${escapeHtml(log.action)}</span>
                                <span class="event-time">${escapeHtml(log.date)}</span>
                            </div>
                            ${refLine}
                            <p class="event-details">${escapeHtml(log.note || "No additional notes.")}</p>
                            <div class="event-meta">
                                <span><i class="material-symbols-rounded" style="font-size:14px; vertical-align:middle;">person</i> ${escapeHtml(log.user || 'System')}</span>
                                ${log.quantity ? `<span><i class="material-symbols-rounded" style="font-size:14px; vertical-align:middle;">inventory_2</i> Qty: ${escapeHtml(log.quantity)}</span>` : ""}
                                ${balanceLine}
                            </div>
                        </div>
                    </div>
                `}).join("");
            }
        } catch (err) {
            container.innerHTML = "<p>Error loading history.</p>";
            console.error(err);
        }

        histModal?.classList.remove('hidden');
    });

    window.closeHistoryModal = function() {
        histModal?.classList.add('hidden');
    };

    document.querySelectorAll('.close-history-modal').forEach(btn => {
        btn.addEventListener('click', window.closeHistoryModal);
    });

    document.getElementById('btn-print-history')?.addEventListener('click', () => window.print());

    window.addEventListener('click', (e) => {
        if (e.target === histModal) {
            window.closeHistoryModal();
        }
    });


    /* ==========================================================
       4. REGISTER ASSET MODAL LOGIC
       ========================================================== */
    window.openAssetModal = function() {
        regModal?.classList.remove('hidden');
    };

    window.closeAssetModal = function() {
        regModal?.classList.add('hidden');
        
        const regForm = document.getElementById('assetEntryForm');
        if (regForm) regForm.reset();

        const fileInput = document.getElementById('product-image-input');
        const imagePreview = document.getElementById('product-image-preview');
        const placeholder = document.getElementById('product-upload-placeholder');
        const previewContainer = document.getElementById('product-preview-container');
        const dropzone = document.getElementById('product-dropzone');

        if (fileInput) fileInput.value = "";
        
        if (imagePreview) {
            imagePreview.removeAttribute('src');
            imagePreview.removeAttribute('alt');
        }
        
        if (placeholder) placeholder.style.display = 'block';
        if (previewContainer) previewContainer.style.display = 'none';

        if (dropzone) {
            dropzone.style.borderColor = '#e2e8f0';
            dropzone.style.backgroundColor = '#f8fafc';
            dropzone.style.cursor = 'pointer';
        }
    };

    document.querySelectorAll('.close-reg-modal').forEach(btn => btn.addEventListener('click', window.closeAssetModal));
    addEquipmentBtn?.addEventListener('click', window.openAssetModal);


    /* ==========================================================
       5. EDIT ASSET MODAL & CHANGE DETECTION LOGIC
       ========================================================== */
    let originalAssetData = {};

    window.openEditModal = function(productData) {
        const editForm = document.getElementById('editAssetForm');
        const updateBtn = document.getElementById('update-asset-btn');

        if (!editModal || !editForm) return;

        editForm.action = `/admin/edit-product/${productData.id}`;
        const offerType = productData.offer || productData.offer_type || "";

        const fields = {
            'edit-product-id': productData.id,
            'edit-type': productData.type,
            'edit-name': productData.name,
            'edit-size': productData.size,     
            'edit-condition': productData.condition,
            'edit-reorder': productData.reorder_level,
            'edit-description': productData.description,
            'edit-offer-type': offerType,
            'edit-rent': productData.rent_price,
            'edit-rent-period': productData.rent_period,
            'edit-price': productData.sale_price
        };

        const costDisplay = document.getElementById('edit-cost-display');
        if (costDisplay) {
            const cost = parseFloat(productData.cost_price);
            costDisplay.innerText = cost > 0
                ? `₱${cost.toLocaleString('en-PH', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
                : 'Not set';
        }

        originalAssetData = { ...fields };

        Object.keys(fields).forEach(id => {
            const el = document.getElementById(id);
            if (el) el.value = fields[id];
        });

        const offerTypeEl = document.getElementById('edit-offer-type');
        if (offerTypeEl) {
            offerTypeEl.dispatchEvent(new Event('change'));
        }

        const previewContainer = document.getElementById('edit-product-preview-container');
        const previewImg = document.getElementById('edit-product-image-preview');
        const placeholder = document.getElementById('edit-product-upload-placeholder');

        if (productData.image && productData.image !== 'None' && productData.image !== '') {
            previewImg.src = `/static/${productData.image}`;
            previewContainer.style.display = 'flex';
            placeholder.style.display = 'none';
        } else {
            previewImg.removeAttribute('src');
            previewContainer.style.display = 'none';
            placeholder.style.display = 'block';
        }

        if (updateBtn) updateBtn.disabled = true;
        editModal.classList.remove('hidden');
    };

    document.getElementById('editAssetForm')?.addEventListener('input', function() {
        const updateBtn = document.getElementById('update-asset-btn');
        const fileInput = document.getElementById('edit-product-image-input');
        
        const currentData = {
            'edit-product-id': document.getElementById('edit-product-id').value,
            'edit-type': document.getElementById('edit-type').value,
            'edit-name': document.getElementById('edit-name').value,
            'edit-size': document.getElementById('edit-size').value,      
            'edit-condition': document.getElementById('edit-condition').value,
            'edit-reorder': document.getElementById('edit-reorder').value,
            'edit-description': document.getElementById('edit-description').value,
            'edit-offer-type': document.getElementById('edit-offer-type').value,
            'edit-rent': document.getElementById('edit-rent').value,
            'edit-rent-period': document.getElementById('edit-rent-period').value,
            'edit-price': document.getElementById('edit-price').value
        };

        const hasChanged = Object.keys(currentData).some(key => 
            String(currentData[key]) !== String(originalAssetData[key])
        );
        const hasNewFile = fileInput && fileInput.files.length > 0;

        if (updateBtn) {
            updateBtn.disabled = !(hasChanged || hasNewFile);
        }
    });

    document.getElementById('edit-offer-type')?.addEventListener('change', () => {
        document.getElementById('editAssetForm')?.dispatchEvent(new Event('input'));
    });
    
    document.getElementById('edit-rent-period')?.addEventListener('change', () => {
        document.getElementById('editAssetForm')?.dispatchEvent(new Event('input'));
    });

    window.closeEditModal = function() {
        const fileInput = document.getElementById('edit-product-image-input');
        const updateBtn = document.getElementById('update-asset-btn');
        
        editModal?.classList.add('hidden');
        
        const previewImg = document.getElementById('edit-product-image-preview');
        if (previewImg) previewImg.removeAttribute('src');
        if (fileInput) fileInput.value = "";
        
        if (updateBtn) {
            const btnText = updateBtn.querySelector('.btn-text');
            const btnSpinner = updateBtn.querySelector('.btn-spinner');
            
            updateBtn.disabled = true;
            if (btnText) btnText.style.opacity = '1';
            if (btnSpinner) btnSpinner.classList.add('hidden');
        }
    };

    document.querySelectorAll('.close-edit-modal').forEach(btn => {
        btn.addEventListener('click', window.closeEditModal);
    });

    document.getElementById('editAssetForm')?.addEventListener('submit', function() {
        const updateBtn = document.getElementById('update-asset-btn');
        const btnText = updateBtn.querySelector('.btn-text');
        const btnSpinner = updateBtn.querySelector('.btn-spinner');

        if (updateBtn) {
            updateBtn.disabled = true;
            updateBtn.style.cursor = 'wait';
            if (btnText) btnText.style.opacity = '0';
            if (btnSpinner) btnSpinner.classList.remove('hidden');
        }
    });


    /* ==========================================================
       6. IMAGE UPLOAD & DRAG-DROP HANDLER
       ========================================================== */
    const setupUpload = (dropzoneId, inputId, placeholderId, previewContainerId, imagePreviewId, resetBtnId) => {
        const dropzone = document.getElementById(dropzoneId);
        const fileInput = document.getElementById(inputId);
        const placeholder = document.getElementById(placeholderId);
        const previewContainer = document.getElementById(previewContainerId);
        const imagePreview = document.getElementById(imagePreviewId);
        const resetBtn = document.getElementById(resetBtnId);

        if (!dropzone || !fileInput || !previewContainer) return;

        const isPreviewVisible = () => window.getComputedStyle(previewContainer).display !== 'none';

        const showPreview = (src) => {
            imagePreview.src = src;
            placeholder.style.display = 'none';
            previewContainer.style.display = 'flex';
            dropzone.style.borderColor = '#10b981';
            dropzone.style.background = '#f0fdf4';
            dropzone.style.cursor = 'default';
        };

        const resetPreview = () => {
            fileInput.value = "";
            if (imagePreview) {
                imagePreview.removeAttribute('src');
                imagePreview.removeAttribute('alt');
            }
            placeholder.style.display = 'block';
            previewContainer.style.display = 'none';
            dropzone.style.borderColor = '#e2e8f0';
            dropzone.style.background = '#f8fafc';
            dropzone.style.cursor = 'pointer';
        };

        dropzone.addEventListener('click', (e) => {
            if (!isPreviewVisible() && !e.target.closest(`#${resetBtnId}`)) {
                fileInput.click();
            }
        });

        fileInput.addEventListener('change', function() {
            const file = this.files[0];
            if (file && file.type.startsWith('image/')) {
                const reader = new FileReader();
                reader.onload = (e) => showPreview(e.target.result);
                reader.readAsDataURL(file);
            } else if (file) {
                alert("Please upload a valid image file.");
                this.value = "";
            }
        });

        if (resetBtn) {
            resetBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                resetPreview();
            });
        }

        ['dragenter', 'dragover'].forEach(event => {
            dropzone.addEventListener(event, (e) => {
                e.preventDefault();
                e.stopPropagation();
                if (!isPreviewVisible()) {
                    dropzone.style.borderColor = '#0ea5e9';
                    dropzone.style.background = '#f0f9ff';
                }
            });
        });

        ['dragleave', 'drop'].forEach(event => {
            dropzone.addEventListener(event, (e) => {
                e.preventDefault();
                e.stopPropagation();
                if (isPreviewVisible()) {
                    dropzone.style.borderColor = '#10b981';
                    dropzone.style.background = '#f0fdf4';
                } else {
                    dropzone.style.borderColor = '#e2e8f0';
                    dropzone.style.background = '#f8fafc';
                }
            });
        });

        dropzone.addEventListener('drop', (e) => {
            if (isPreviewVisible()) return;
            const files = e.dataTransfer.files;
            if (files.length > 0 && files[0].type.startsWith('image/')) {
                fileInput.files = files;
                fileInput.dispatchEvent(new Event('change'));
            }
        });

        resetPreview();
    };

    setupUpload('product-dropzone', 'product-image-input', 'product-upload-placeholder', 'product-preview-container', 'product-image-preview', 'reset-product-upload');
    setupUpload('edit-product-dropzone', 'edit-product-image-input', 'edit-product-upload-placeholder', 'edit-product-preview-container', 'edit-product-image-preview', 'reset-edit-upload');


    /* ==========================================================
       7. INVENTORY TABLE INTERACTIONS
       ========================================================== */
        if (inventoryTable) {
            inventoryTable.addEventListener('click', (e) => {
                const editBtn = e.target.closest('.dropdown-item.edit');
                const deleteBtn = e.target.closest('.dropdown-item.delete');

                if (editBtn) {
                    const productData = {
                        id: editBtn.dataset.id,
                        type: editBtn.dataset.type || '',
                        name: editBtn.dataset.name || '',
                        size: editBtn.dataset.size || '',          // <--- ADD THIS LINE HERE
                        cost_price: editBtn.dataset.costPrice || 0,
                        stock: editBtn.dataset.stock || 0,
                        condition: editBtn.dataset.condition || 'N/A',
                        reorder_level: editBtn.dataset.reorder || 0,
                        offer_type: editBtn.dataset.offer || '',
                        rent_period: editBtn.dataset.period || 'Monthly',
                        rent_price: editBtn.dataset.rent || 0,
                        sale_price: editBtn.dataset.price || 0,
                        description: (editBtn.dataset.description === "None" || !editBtn.dataset.description) ? "" : editBtn.dataset.description.trim(),
                        image: editBtn.dataset.image || ''
                    };
                    window.openEditModal(productData);
                } else if (deleteBtn) {
                    const row = deleteBtn.closest('tr');
                    const assetTag = row.cells[1].innerText;
                    console.log("Deleting...", assetTag);
                }
            });
        }


    /* ==========================================================
       8. TRANSACTION & FORM DYNAMIC ROUTING / CALCULATIONS
       ========================================================== */
    document.querySelectorAll('.asset-action-btn.rent').forEach(btn => {
        btn.addEventListener('click', () => window.location.href = '/admin/transactions?type=Rental');
    });

    document.addEventListener('click', function(e) {
        const btn = e.target.closest('.asset-action-btn.purchase');
        if (btn) window.location.href = '/admin/transactions?type=Sale';
    });

    const rentForm = document.getElementById('rentEntryForm');
    const rentRateInput = document.getElementById('rent-rate-display');
    const depositInput = document.getElementById('security-deposit-input');
    const totalDisplay = document.querySelector('.total-amount-display');

    if (rentForm) {
        rentForm.addEventListener('input', () => {
            const rate = parseFloat(rentRateInput?.value) || 0;
            const deposit = parseFloat(depositInput?.value) || 0;
            if (totalDisplay) {
                const total = rate + deposit;
                totalDisplay.textContent = `₱${total.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
            }
        });
    }

    const customerSelect = document.getElementById('rental-customer-id');
    const idStatusIcon = document.getElementById('customer-id-status');

    if (customerSelect && idStatusIcon) {
        customerSelect.addEventListener('change', function() {
            if (this.value) {
                idStatusIcon.innerText = 'check_circle';
                idStatusIcon.style.color = '#10b981'; 
            } else {
                idStatusIcon.innerText = 'radio_button_unchecked';
                idStatusIcon.style.color = '#cbd5e1';
            }
        });
    }


    /* ==========================================================
       9. PRODUCT TYPE CONDITIONAL PRICING CONFIGURATORS
       ========================================================== */
    // Registration Offer Type Toggle
    const offerTypeSelect = document.getElementById('reg-offer-type');
    const pricingRow = document.getElementById('pricing-row-container');
    const rentField = document.getElementById('rent-field');
    const saleField = document.getElementById('sale-field');

    if (offerTypeSelect && pricingRow && rentField && saleField) {
        const rentInput = rentField.querySelector('input[name="rent_price"]');
        const saleInput = saleField.querySelector('input[name="sale_price"]');

        offerTypeSelect.addEventListener('change', function() {
            const val = this.value;
            rentField.style.display = 'none';
            saleField.style.display = 'none';

            if (val === 'Rental') {
                rentField.style.display = 'block';
                pricingRow.style.gridTemplateColumns = '200px 260px'; 
                if (saleInput) saleInput.value = ''; 
            } else if (val === 'Sale') {
                saleField.style.display = 'block';
                pricingRow.style.gridTemplateColumns = '200px 180px'; 
                if (rentInput) rentInput.value = ''; 
            } else if (val === 'Both') {
                rentField.style.display = 'block';
                saleField.style.display = 'block';
                pricingRow.style.gridTemplateColumns = '200px 260px 180px'; 
            }
        });
    }

    // Edit Modal Offer Type Toggle
    const editOfferType = document.getElementById('edit-offer-type');
    const editPricingRow = document.getElementById('edit-pricing-row-container');
    const editRentField = document.getElementById('edit-rent-field');
    const editSaleField = document.getElementById('edit-sale-field');

    if (editOfferType && editPricingRow && editRentField && editSaleField) {
        const editRentInput = editRentField.querySelector('input[name="rent_price"]');
        const editSaleInput = editSaleField.querySelector('input[name="sale_price"]');

        editOfferType.addEventListener('change', function() {
            const val = this.value;
            editRentField.style.display = 'none';
            editSaleField.style.display = 'none';

            if (val === 'Rental') {
                editRentField.style.display = 'block';
                editPricingRow.style.gridTemplateColumns = '200px 260px'; 
                if (editSaleInput) editSaleInput.value = ''; 
            } else if (val === 'Sale') {
                editSaleField.style.display = 'block';
                editPricingRow.style.gridTemplateColumns = '200px 180px'; 
                if (editRentInput) editRentInput.value = '';
            }
        });
    }

});

/*============= ADDSTOCKMODAL =============*/

document.addEventListener('DOMContentLoaded', function() {
    const stockModal = document.getElementById('addStockModal');
    const stockForm = document.getElementById('addStockForm');
    const stockInput = document.getElementById('stock-increment-input');
    
    // Changed: unitCostInput is now the typed input, totalCostInput is the hidden/calculated field
    const unitCostInput = document.getElementById('stock-unit-cost-input');
    const totalCostInput = document.getElementById('stock-total-cost-input');
    
    const unitCostPreview = document.getElementById('unit-cost-preview');
    const calculatedTotalDisplay = document.getElementById('calculated-total-cost');
    const currentStockDisplay = document.getElementById('current-stock-display');
    const newTotalDisplay = document.getElementById('new-total-display');
    const stockEquipName = document.getElementById('stock-equipment-name');
    const reasonInput = document.getElementById('stock-reason-input');

    let currentBaseStock = 0;
    let activeProductId = null;

    // --- 1. Open Modal ---
    document.addEventListener('click', function(e) {
        const btn = e.target.closest('.add-stock-trigger');
        if (btn) {
            activeProductId = btn.dataset.id;
            currentBaseStock = parseInt(btn.dataset.stock) || 0;

            stockEquipName.innerText = btn.dataset.name;
            currentStockDisplay.innerText = `${currentBaseStock} Units`;
            newTotalDisplay.innerText = `${currentBaseStock} Units`;

            // Reset fields
            stockInput.value = '';
            if (unitCostInput) unitCostInput.value = '';
            totalCostInput.value = '';
            reasonInput.value = '';
            unitCostPreview.style.display = 'none';

            stockModal.classList.remove('hidden');
        }

        if (e.target.closest('.close-stock-modal')) {
            stockModal.classList.add('hidden');
        }
    });

    // --- 2. Live Stock Calculation ---
    stockInput.addEventListener('input', function() {
        const qty = parseInt(this.value) || 0;
        const total = currentBaseStock + qty;
        newTotalDisplay.innerText = `${total} Units`;
        newTotalDisplay.style.color = total < currentBaseStock ? "#ef4444" : "#52B788";
        calculateTotalCost();
    });

    // --- 3. Live Total Cost Calculation based on Unit Cost ---
    if (unitCostInput) {
        unitCostInput.addEventListener('input', calculateTotalCost);
    }

    function calculateTotalCost() {
        const qty = parseFloat(stockInput.value) || 0;
        const unitCost = parseFloat(unitCostInput.value) || 0;

        if (qty > 0 && unitCost > 0) {
            const total = qty * unitCost;
            calculatedTotalDisplay.innerText = '₱' + total.toLocaleString('en-US', { 
                minimumFractionDigits: 2, 
                maximumFractionDigits: 2 
            });
            totalCostInput.value = total.toFixed(2);
            unitCostPreview.style.display = 'block';
        } else {
            unitCostPreview.style.display = 'none';
            totalCostInput.value = '';
        }
    }

    // --- 4. Form Submission ---
    stockForm.addEventListener('submit', function(e) {
        e.preventDefault();

        const increment = parseInt(stockInput.value);
        const totalAmountPaid = parseFloat(totalCostInput.value) || null;
        const reason = reasonInput.value.trim();

        if (!increment || increment <= 0) {
            alert('Please enter a valid quantity.');
            return;
        }

        const submitBtn = this.querySelector('button[type="submit"]');
        submitBtn.disabled = true;
        submitBtn.innerText = 'Processing...';

        fetch(`/admin/update_stock/${activeProductId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                increment: increment,
                total_amount_paid: totalAmountPaid,
                reason: reason
            })
        })
        .then(res => res.json())
        .then(data => {
            if (data.success) {
                stockModal.classList.add('hidden');
                window.location.reload();
            } else {
                alert(data.message || 'Failed to update stock.');
                submitBtn.disabled = false;
                submitBtn.innerText = 'Confirm Restock';
            }
        })
        .catch(err => {
            console.error('Stock Update Error:', err);
            alert('A network error occurred.');
            submitBtn.disabled = false;
            submitBtn.innerText = 'Confirm Restock';
        });
    });
});

/*============= END OF ADDSTOCKMODAL =============*/


/*============= DELETEMODAL =============*/
const deleteModal = document.getElementById('deleteAssetModal');
const deleteForm = document.getElementById('deleteAssetForm');
const closeButtons = document.querySelectorAll('.close-modal-btn');
let assetIdToDelete = null;

document.addEventListener('click', function(e) {
    const deleteBtn = e.target.closest('.dropdown-item.delete');
    
    if (deleteBtn) {
        const row = deleteBtn.closest('tr');
        assetIdToDelete = row.getAttribute('data-id');
        
        // Grab the name from the 3rd cell (index 2)
        const assetName = row.cells[2].innerText; 
        const deleteNameDisplay = document.getElementById('delete-asset-name');
        if (deleteNameDisplay) deleteNameDisplay.innerText = assetName;

        // DYNAMICALLY SET THE FORM ACTION URL
        // Assumes your route is /admin/delete-product/<id>
        if (deleteForm) {
            deleteForm.action = `/admin/delete-product/${assetIdToDelete}`;
        }

        deleteModal.classList.remove('hidden');
    }
});

// Logic to hide the modal
closeButtons.forEach(button => {
    button.addEventListener('click', () => {
        deleteModal.classList.add('hidden');
        assetIdToDelete = null;
    });
});

// Close when clicking outside the modal content
window.addEventListener('click', (e) => {
    if (e.target === deleteModal) {
        deleteModal.classList.add('hidden');
    }
});
/*============= END OF DELETEMODAL =============*/



/*============= START OF PAGINATION =============*/
document.addEventListener('DOMContentLoaded', function() {
    
    const updateFilters = () => {
        const searchVal = document.getElementById('table-search')?.value.trim();
        const limitVal = document.getElementById('row-limit-select')?.value;
        const typeVal = document.getElementById('type-filter')?.value;
        const fullVal = document.getElementById('fulfillment-filter')?.value;

        const urlParams = new URLSearchParams();
        
        if (searchVal) urlParams.set('q', searchVal);
        if (limitVal) urlParams.set('limit', limitVal);
        if (typeVal) urlParams.set('type', typeVal);
        if (fullVal) urlParams.set('fulfillment', fullVal);
        
        urlParams.set('page', 1);

        window.location.href = window.location.pathname + '?' + urlParams.toString();
    };

    const searchInput = document.getElementById('table-search');
    let searchTimer;

    if (searchInput) {
        searchInput.addEventListener('keyup', (e) => {
            clearTimeout(searchTimer);
            if (e.key === 'Enter') {
                updateFilters();
            } else {
                searchTimer = setTimeout(updateFilters, 800);
            }
        });
    }

    const filters = ['row-limit-select', 'type-filter', 'fulfillment-filter'];
    filters.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.addEventListener('change', updateFilters);
    });

    const clearBtn = document.getElementById('clear-filters-btn');
    if (clearBtn) {
        clearBtn.addEventListener('click', () => {
            window.location.href = window.location.pathname;
        });
    }

    const jumpBtn = document.querySelector('.jump-btn');
    const jumpInput = document.getElementById('jump-page-input');

    const handleJump = () => {
        const page = parseInt(jumpInput.value);
        const maxPage = parseInt(jumpInput.getAttribute('max'));
        
        if (page >= 1 && page <= maxPage) {
            const urlParams = new URLSearchParams(window.location.search);
            urlParams.set('page', page);
            window.location.href = window.location.pathname + '?' + urlParams.toString();
        } else {
            jumpInput.style.borderColor = "#ef4444";
            setTimeout(() => jumpInput.style.borderColor = "#cbd5e1", 2000);
        }
    };

    if (jumpBtn) jumpBtn.addEventListener('click', handleJump);

    if (jumpInput) {
        jumpInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') handleJump();
        });
    }
});
/*============= END OF PAGINATION =============*/



/*============= START OF FLASK MESSAGE =============*/
document.addEventListener("DOMContentLoaded", function () {
    const alerts = document.querySelectorAll(".auto-dismiss");

    alerts.forEach(alert => {
        const duration = 5000; // 5 seconds (change to 3000 for 3 sec)
        const progressBar = alert.querySelector(".progress-bar");

        // Animate progress bar
        progressBar.style.width = "100%";
        progressBar.style.transition = `width ${duration}ms linear`;

        setTimeout(() => {
            progressBar.style.width = "0%";
        }, 10);

        // Auto close alert
        setTimeout(() => {
            let bsAlert = new bootstrap.Alert(alert);
            bsAlert.close();
        }, duration);
    });
});
/*============= END OF FLASK MESSAGE =============*/